
"""
network.py 

Defines Network class which contains cell objects and network-realated methods

Contributors: salvadordura@gmail.com
"""

from matplotlib.pylab import array, sin, cos, tan, exp, sqrt, mean, inf, rand
from random import seed, random, randint, sample, uniform, triangular, gauss, betavariate, expovariate, gammavariate
from time import time
from numbers import Number
from copy import copy
from neuron import h  # import NEURON
import framework as f


class Network(object):

    ###############################################################################
    # initialize variables
    ###############################################################################
    def __init__(self, params = None):
        self.params = params

    ###############################################################################
    # Set network params
    ###############################################################################
    def setParams(self, params):
        self.params = params

    ###############################################################################
    # Instantiate network populations (objects of class 'Pop')
    ###############################################################################
    def createPops(self):
        self.pops = []  # list to store populations ('Pop' objects)
        for popParam in self.params['popParams']: # for each set of population paramseters 
            self.pops.append(f.Pop(popParam))  # instantiate a new object of class Pop and add to list pop

        return self.pops


    ###############################################################################
    # Create Cells
    ###############################################################################
    def createCells(self):
        f.pc.barrier()
        f.sim.timing('start', 'createTime')
        if f.rank==0: 
            print("\nCreating simulation of %i cell populations for %0.1f s on %i hosts..." % (len(self.pops), f.cfg['duration']/1000.,f.nhosts)) 
        self.lid2gid = [] # Empty list for storing local index -> GID (index = local id; value = gid)
        self.gid2lid = {} # Empty dict for storing GID -> local index (key = gid; value = local id) -- ~x6 faster than .index() 
        self.lastGid = 0  # keep track of last cell gid 
        self.cells = []
        for ipop in self.pops: # For each pop instantiate the network cells (objects of class 'Cell')
            newCells = ipop.createCells() # create cells for this pop using Pop method
            self.cells.extend(newCells)  # add to list of cells
            f.pc.barrier()
            if f.rank==0 and f.cfg['verbose']: print('Instantiated %d cells of population %s'%(len(newCells), ipop.tags['popLabel']))    
        f.simData.update({name:h.Vector(1e4).resize(0) for name in ['spkt','spkid']})
        print('  Number of cells on node %i: %i ' % (f.rank,len(self.cells))) 
        f.pc.barrier()
        f.sim.timing('stop', 'createTime')
        if f.rank == 0 and f.cfg['timing']: print('  Done; cell creation time = %0.2f s.' % f.timing['createTime'])

        return f.net.cells
    
    ###############################################################################
    #  Add stims
    ###############################################################################
    def addStims(self):
        f.sim.timing('start', 'stimsTime')
        if 'stimParams' in self.params:
            if f.rank==0: 
                print('Adding stims...')
                
            if f.nhosts > 1: # Gather tags from all cells 
                allCellTags = f.sim.gatherAllCellTags()  
            else:
                allCellTags = {cell.gid: cell.tags for cell in self.cells}
            # allPopTags = {i: pop.tags for i,pop in enumerate(self.pops)}  # gather tags from pops so can connect NetStim pops

            sources = self.params['stimParams']['sourceList']

            for stim in self.params['stimParams']['stimList']:  # for each conn rule or parameter set
                if 'sec' not in stim: stim['sec'] = None  # if section not specified, make None (will be assigned to first section in cell)
                
                source = next((source for source in sources if source['label'] == stim['source']), None)

                postCellsTags = allCellTags
                for condKey,condValue in stim['conditions'].iteritems():  # Find subset of cells that match postsyn criteria
                    if condKey in ['x','y','z','xnorm','ynorm','znorm']:
                        postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if condValue[0] <= tags[condKey] < condValue[1]}  # dict with post Cell objects}  # dict with pre cell tags
                    elif condKey == 'cellList':
                        pass
                    elif isinstance(condValue, list): 
                        postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if tags[condKey] in condValue}  # dict with post Cell objects
                    else:
                        postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if tags[condKey] == condValue}  # dict with post Cell objects
                    
                if 'cellList' in stim['conditions']:
                    orderedPostGids = sorted(postCellsTags.keys())
                    gidList = [orderedPostGids[i] for i in stim['conditions']['cellList']]
                    postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if gid in gidList}

                for postCellGid in postCellsTags:  # for each postsyn cell
                    if postCellGid in f.net.lid2gid:  # check if postsyn is in this node's list of gids
                        postCell = f.net.cells[f.net.gid2lid[postCellGid]]  # get Cell object 
                        params = {'sec': stim['sec'], 
                                'loc': stim['loc'],
                                'delay': source['delay'],
                                'dur': source['dur'],
                                'amp': source['amp']}
                        if source['type'] == 'IClamp':
                            postCell.addIClamp(params)  # call cell method to add connections

            f.sim.timing('stop', 'stimsTime')

            return [cell.stims for cell in f.net.cells]


    ###############################################################################
    # Connect Cells
    ###############################################################################
    def connectCells(self):
        # Instantiate network connections based on the connectivity rules defined in params
        f.sim.timing('start', 'connectTime')
        if f.rank==0: 
            print('Making connections...')

        if f.nhosts > 1: # Gather tags from all cells 
            allCellTags = f.sim.gatherAllCellTags()  
        else:
            allCellTags = {cell.gid: cell.tags for cell in self.cells}
        allPopTags = {i: pop.tags for i,pop in enumerate(self.pops)}  # gather tags from pops so can connect NetStim pops

        for connParamTemp in self.params['connParams']:  # for each conn rule or parameter set
            connParam = connParamTemp.copy()
            if 'sec' not in connParam: connParam['sec'] = None  # if section not specified, make None (will be assigned to first section in cell)
            if 'synMech' not in connParam: connParam['synMech'] = None  # if synaptic mechanism not specified, make None (will be assigned to first synaptic mechanism in cell)  
            if 'threshold' not in connParam: connParam['threshold'] = f.net.params['defaultThreshold']  # if no threshold specified, make None (will be assigned default value)
            if 'seed' not in connParam: connParam['threshold'] = f.net.params['defaultThreshold']  # if no threshold specified, make None (will be assigned default value)

            if 'weight' not in connParam: connParam['weight'] = f.net.params['defaultWeight'] # if no weight, set default
            if 'delay' not in connParam: connParam['delay'] = f.net.params['defaultDelay'] # if no delay, set default

            preCellsTags = dict(allCellTags)  # initialize with all presyn cells (make copy)
            prePops = allPopTags  # initialize with all presyn pops

            for condKey,condValue in connParam['preTags'].iteritems():  # Find subset of cells that match presyn criteria
                if condKey in ['x','y','z','xnorm','ynorm','znorm']:
                    preCellsTags = {gid: tags for (gid,tags) in preCellsTags.iteritems() if condValue[0] <= tags[condKey] < condValue[1]}  # dict with pre cell tags
                    prePops = {}
                else:
                    if isinstance(condValue, list): 
                        preCellsTags = {gid: tags for (gid,tags) in preCellsTags.iteritems() if tags[condKey] in condValue}  # dict with pre cell tags
                        prePops = {i: tags for (i,tags) in prePops.iteritems() if (condKey in tags) and (tags[condKey] in condValue)}
                    else:
                        preCellsTags = {gid: tags for (gid,tags) in preCellsTags.iteritems() if tags[condKey] == condValue}  # dict with pre cell tags
                        prePops = {i: tags for (i,tags) in prePops.iteritems() if (condKey in tags) and (tags[condKey] == condValue)}
                    

            if not preCellsTags: # if no presyn cells, check if netstim
                if any (prePopTags['cellModel'] == 'NetStim' for prePopTags in prePops.values()):
                    for prePop in prePops.values():
                        if not 'start' in prePop: prePop['start'] = 5  # add default start time
                        if not 'number' in prePop: prePop['number'] = 1e12  # add default number 
                        if not 'source' in prePop: prePop['source'] = 'random'  # add default source
                    preCellsTags = prePops
            
            if preCellsTags:  # only check post if there are pre
                postCellsTags = allCellTags
                for condKey,condValue in connParam['postTags'].iteritems():  # Find subset of cells that match postsyn criteria
                    if condKey in ['x','y','z','xnorm','ynorm','znorm']:
                        postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if condValue[0] <= tags[condKey] < condValue[1]}  # dict with post Cell objects}  # dict with pre cell tags
                    elif isinstance(condValue, list): 
                        postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if tags[condKey] in condValue}  # dict with post Cell objects
                    else:
                        postCellsTags = {gid: tags for (gid,tags) in postCellsTags.iteritems() if tags[condKey] == condValue}  # dict with post Cell objects


                if 'connFunc' not in connParam:  # if conn function not specified, select based on params
                    if 'probability' in connParam: connParam['connFunc'] = 'probConn'  # probability based func
                    elif 'convergence' in connParam: connParam['connFunc'] = 'convConn'  # convergence function
                    elif 'divergence' in connParam: connParam['connFunc'] = 'divConn'  # divergence function
                    elif 'connList' in connParam: connParam['connFunc'] = 'fromListConn'  # from list function
                    else: connParam['connFunc'] = 'fullConn'  # convergence function

                connFunc = getattr(self, connParam['connFunc'])  # get function name from params
                if preCellsTags and postCellsTags:
                    self._strToFunc(preCellsTags, postCellsTags, connParam)  # convert strings to functions (for the delay, and probability params)
                    connFunc(preCellsTags, postCellsTags, connParam)  # call specific conn function
        
        print('  Number of connections on node %i: %i ' % (f.rank, sum([len(cell.conns) for cell in f.net.cells])))
        f.pc.barrier()
        f.sim.timing('stop', 'connectTime')
        if f.rank == 0 and f.cfg['timing']: print('  Done; cell connection time = %0.2f s.' % f.timing['connectTime'])

        return [cell.conns for cell in f.net.cells]

    ###############################################################################
    # Convert string to function
    ###############################################################################
    def _strToFunc(self, preCellsTags, postCellsTags, connParam):
        # list of params that have a function passed in as a string
        paramsStrFunc = [param for param in ['weight', 'delay', 'probability', 'convergence', 'divergence'] if param in connParam and isinstance(connParam[param], str)]  

        # dict to store correspondence between string and actual variable
        dictVars = {}  
        dictVars['pre_x']       = lambda preTags,postTags: preTags['x'] 
        dictVars['pre_y']       = lambda preTags,postTags: preTags['y'] 
        dictVars['pre_z']       = lambda preTags,postTags: preTags['z'] 
        dictVars['pre_xnorm']   = lambda preTags,postTags: preTags['xnorm'] 
        dictVars['pre_ynorm']   = lambda preTags,postTags: preTags['ynorm'] 
        dictVars['pre_znorm']   = lambda preTags,postTags: preTags['znorm'] 
        dictVars['post_x']      = lambda preTags,postTags: postTags['x'] 
        dictVars['post_y']      = lambda preTags,postTags: postTags['y'] 
        dictVars['post_z']      = lambda preTags,postTags: postTags['z'] 
        dictVars['post_xnorm']  = lambda preTags,postTags: postTags['xnorm'] 
        dictVars['post_ynorm']  = lambda preTags,postTags: postTags['ynorm'] 
        dictVars['post_znorm']  = lambda preTags,postTags: postTags['znorm'] 
        dictVars['dist_x']      = lambda preTags,postTags: abs(preTags['x'] - postTags['x'])
        dictVars['dist_y']      = lambda preTags,postTags: abs(preTags['y'] - postTags['y']) 
        dictVars['dist_z']      = lambda preTags,postTags: abs(preTags['z'] - postTags['z'])
        dictVars['dist_3D']    = lambda preTags,postTags: sqrt((preTags['x'] - postTags['x'])**2 +
                                (preTags['y'] - postTags['y'])**2 + 
                                (preTags['z'] - postTags['z'])**2)
        dictVars['dist_2D']     = lambda preTags,postTags: sqrt((preTags['x'] - postTags['x'])**2 +
                                (preTags['z'] - postTags['z'])**2)
        dictVars['dist_xnorm']  = lambda preTags,postTags: abs(preTags['xnorm'] - postTags['xnorm'])
        dictVars['dist_ynorm']  = lambda preTags,postTags: abs(preTags['ynorm'] - postTags['ynorm']) 
        dictVars['dist_znorm']  = lambda preTags,postTags: abs(preTags['znorm'] - postTags['znorm'])
        dictVars['dist_norm3D'] = lambda preTags,postTags: sqrt((preTags['xnorm'] - postTags['xnorm'])**2 +
                                sqrt(preTags['ynorm'] - postTags['ynorm']) + 
                                sqrt(preTags['znorm'] - postTags['znorm']))
        dictVars['dist_norm2D'] = lambda preTags,postTags: sqrt((preTags['xnorm'] - postTags['xnorm'])**2 +
                                sqrt(preTags['znorm'] - postTags['znorm']))
        # add netParams variables
        for k,v in f.net.params.iteritems():
            if isinstance(v, Number):
                dictVars[k] = v

        # for each parameter containing a function
        for paramStrFunc in paramsStrFunc:
            strFunc = connParam[paramStrFunc]  # string containing function
            strVars = [var for var in dictVars.keys() if var in strFunc and var+'norm' not in strFunc]  # get list of variables used (eg. post_ynorm or dist_xyz)
            lambdaStr = 'lambda ' + ','.join(strVars) +': ' + strFunc # convert to lambda function 
            lambdaFunc = eval(lambdaStr)
       
            # initialize randomizer in case used in function
            seed(f.sim.id32('%d'%(f.cfg['seeds']['conn'])))

            if paramStrFunc in ['probability']:
                # replace function with dict of values derived from function (one per pre+post cell)
                connParam[paramStrFunc+'Func'] = {(preGid,postGid): lambdaFunc(
                    **{strVar: dictVars[strVar] if isinstance(dictVars[strVar], Number) else dictVars[strVar](preCellTags, postCellTags) for strVar in strVars})  
                    for preGid,preCellTags in preCellsTags.iteritems() for postGid,postCellTags in postCellsTags.iteritems()}

            elif paramStrFunc in ['convergence']:
                # replace function with dict of values derived from function (one per post cell)
                connParam[paramStrFunc+'Func'] = {postGid: lambdaFunc(
                    **{strVar: dictVars[strVar] if isinstance(dictVars[strVar], Number) else dictVars[strVar](None, postCellTags) for strVar in strVars}) 
                    for postGid,postCellTags in postCellsTags.iteritems()}

            elif paramStrFunc in ['divergence']:
                # replace function with dict of values derived from function (one per post cell)
                connParam[paramStrFunc+'Func'] = {preGid: lambdaFunc(
                    **{strVar: dictVars[strVar] if isinstance(dictVars[strVar], Number) else dictVars[strVar](preCellTags, None) for strVar in strVars}) 
                    for preGid, preCellTags in preCellsTags.iteritems()}

            else:
                # store lambda function and func vars in connParam (for weight and delay, since only calculated for certain conns)
                connParam[paramStrFunc+'Func'] = lambdaFunc
                connParam[paramStrFunc+'FuncVars'] = {strVar: dictVars[strVar] for strVar in strVars} 
 

    ###############################################################################
    ### Full connectivity
    ###############################################################################
    def fullConn(self, preCellsTags, postCellsTags, connParam):
        ''' Generates connections between all pre and post-syn cells '''
        if f.cfg['verbose']: print 'Generating set of all-to-all connections...'

        # list of params that can have a lambda function
        paramsStrFunc = [param for param in ['weightFunc', 'delayFunc'] if param in connParam] 
        for paramStrFunc in paramsStrFunc:
            # replace lambda function (with args as dict of lambda funcs) with list of values
            seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+preCellsTags.keys()[0]+postCellsTags.keys()[0])))
            connParam[paramStrFunc[:-4]+'List'] = {(preGid,postGid): connParam[paramStrFunc](**{k:v if isinstance(v, Number) else v(preCellTags,postCellTags) for k,v in connParam[paramStrFunc+'Vars'].iteritems()})  
                    for preGid,preCellTags in preCellsTags.iteritems() for postGid,postCellTags in postCellsTags.iteritems()}
         
        for postCellGid in postCellsTags:  # for each postsyn cell
            if postCellGid in f.net.lid2gid:  # check if postsyn is in this node's list of gids
                postCell = f.net.cells[f.net.gid2lid[postCellGid]]  # get Cell object 
                for preCellGid, preCellTags in preCellsTags.iteritems():  # for each presyn cell
                    if preCellTags['cellModel'] == 'NetStim':  # if NetStim
                        self._addCellNetStim(connParam, preCellTags, preCellGid, postCellGid) # cell method to add connection               
                    elif preCellGid != postCellGid: # if not self-connection
                        self._addCellConn(connParam, preCellGid, postCellGid) # add connection


    ###############################################################################
    ### Probabilistic connectivity 
    ###############################################################################
    def probConn(self, preCellsTags, postCellsTags, connParam):
        ''' Generates connections between all pre and post-syn cells based on probability values'''
        if f.cfg['verbose']: print 'Generating set of probabilistic connections...'

        seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+preCellsTags.keys()[0]+postCellsTags.keys()[0])))  
        allRands = {(preGid,postGid): random() for preGid in preCellsTags for postGid in postCellsTags}  # Create an array of random numbers for checking each connection

        for postCellGid,postCellTags in postCellsTags.iteritems():  # for each postsyn cell
            if postCellGid in f.net.lid2gid:  # check if postsyn is in this node
                postCell = f.net.cells[f.net.gid2lid[postCellGid]]  # get Cell object
                for preCellGid, preCellTags in preCellsTags.iteritems():  # for each presyn cell
                    probability = connParam['probabilityFunc'][preCellGid,postCellGid] if 'probabilityFunc' in connParam else connParam['probability']
                    if 'weightFunc' in connParam: 
                        connParam['weightFuncArgs'] = {k:v if isinstance(v, Number) else v(preCellTags,postCellTags) for k,v in connParam['weightFuncVars'].iteritems()}  # call lambda functions to get weight func args
                    if 'delayFunc' in connParam: 
                        connParam['delayFuncArgs'] = {k:v if isinstance(v, Number) else v(preCellTags,postCellTags) for k,v in connParam['delayFuncVars'].iteritems()}  # call lambda functions to get delay func args
                    if probability >= allRands[preCellGid,postCellGid]:
                        seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+postCellGid+preCellGid)))  
                        if preCellTags['cellModel'] == 'NetStim':  # if NetStim
                            self._addCellNetStim(connParam, preCellTags, preCellGid, postCellGid) # cell method to add connection               
                        elif preCellGid != postCellGid: # if not self-connection
                           self._addCellConn(connParam, preCellGid, postCellGid) # add connection


    ###############################################################################
    ### Convergent connectivity 
    ###############################################################################
    def convConn(self, preCellsTags, postCellsTags, connParam):
        ''' Generates connections between all pre and post-syn cells based on probability values'''
        if f.cfg['verbose']: print 'Generating set of convergent connections...'
               
        for postCellGid,postCellTags in postCellsTags.iteritems():  # for each postsyn cell
            if postCellGid in f.net.lid2gid:  # check if postsyn is in this node
                postCell = f.net.cells[f.net.gid2lid[postCellGid]]  # get Cell object
                convergence = connParam['convergenceFunc'][postCellGid] if 'convergenceFunc' in connParam else connParam['convergence']  # num of presyn conns / postsyn cell
                convergence = max(min(int(round(convergence)), len(preCellsTags)), 0)
                seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+postCellGid)))  
                preCellsSample = sample(preCellsTags.keys(), convergence)  # selected gids of presyn cells
                preCellsConv = {k:v for k,v in preCellsTags.iteritems() if k in preCellsSample}  # dict of selected presyn cells tags
                for preCellGid, preCellTags in preCellsConv.iteritems():  # for each presyn cell
                    if 'weightFunc' in connParam:
                        connParam['weightFuncArgs'] = {k:v if isinstance(v, Number) else v(preCellTags,postCellTags) for k,v in connParam['weightFuncVars'].iteritems()}  # call lambda functions to get weight func args
                    if 'delayFunc' in connParam: 
                        connParam['delayFuncArgs'] = {k:v if isinstance(v, Number) else v(preCellTags, postCellTags) for k,v in connParam['delayFuncVars'].iteritems()}  # call lambda functions to get delay func args
                    seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+postCellGid+preCellGid)))  
                    if preCellTags['cellModel'] == 'NetStim':  # if NetStim
                        print 'Error: Convergent connectivity for NetStims is not implemented'
                    elif preCellGid != postCellGid: # if not self-connection   
                        self._addCellConn(connParam, preCellGid, postCellGid) # add connection


    ###############################################################################
    ### Divergent connectivity 
    ###############################################################################
    def divConn(self, preCellsTags, postCellsTags, connParam):
        ''' Generates connections between all pre and post-syn cells based on probability values'''
        if f.cfg['verbose']: print 'Generating set of divergent connections...'
         
        for preCellGid, preCellTags in preCellsTags.iteritems():  # for each presyn cell
            divergence = connParam['divergenceFunc'][preCellGid] if 'divergenceFunc' in connParam else connParam['divergence']  # num of presyn conns / postsyn cell
            divergence = max(min(int(round(divergence)), len(postCellsTags)), 0)
            seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+preCellGid)))  
            postCellsSample = sample(postCellsTags, divergence)  # selected gids of postsyn cells
            postCellsDiv = {postGid:postTags  for postGid,postTags in postCellsTags.iteritems() if postGid in postCellsSample and postGid in f.net.lid2gid}  # dict of selected postsyn cells tags
            for postCellGid, postCellTags in postCellsDiv.iteritems():  # for each postsyn cell
                postCell = f.net.cells[f.net.gid2lid[postCellGid]]
                if 'weightFunc' in connParam:
                    connParam['weightFuncArgs'] = {k:v if isinstance(v, Number) else v(preCellTags,postCellTags) for k,v in connParam['weightFuncVars'].iteritems()}  # call lambda functions to get weight func args
                if 'delayFunc' in connParam: 
                    connParam['delayFuncArgs'] = {k:v if isinstance(v, Number) else v(preCellTags, postCellTags) for k,v in connParam['delayFuncVars'].iteritems()}  # call lambda functions to get delay func args
                seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+postCellGid+preCellGid)))  
                if preCellTags['cellModel'] == 'NetStim':  # if NetStim
                    print 'Error: Divergent connectivity for NetStims is not implemented'           
                elif preCellGid != postCellGid: # if not self-connection
                    self._addCellConn(connParam, preCellGid, postCellGid) # add connection

                    
    ###############################################################################
    ### From list connectivity 
    ###############################################################################
    def fromListConn(self, preCellsTags, postCellsTags, connParam):
        ''' Generates connections between all pre and post-syn cells based list of relative cell ids'''
        if f.cfg['verbose']: print 'Generating set of connections from list...'

        # list of params that can have a lambda function
        paramsStrFunc = [param for param in ['weightFunc', 'delayFunc'] if param in connParam] 
        for paramStrFunc in paramsStrFunc:
            # replace lambda function (with args as dict of lambda funcs) with list of values
            seed(f.sim.id32('%d'%(f.cfg['seeds']['conn']+preCellsTags.keys()[0]+postCellsTags.keys()[0])))
            connParam[paramStrFunc[:-4]+'List'] = {(preGid,postGid): connParam[paramStrFunc](**{k:v if isinstance(v, Number) else v(preCellTags,postCellTags) for k,v in connParam[paramStrFunc+'Vars'].iteritems()})  
                    for preGid,preCellTags in preCellsTags.iteritems() for postGid,postCellTags in postCellsTags.iteritems()}

        if isinstance(connParam['weight'], list): connParam['weightFromList'] = list(connParam['weight'])  # if weight is a list, copy to weightList
        if isinstance(connParam['delay'], list): connParam['delayFromList'] = list(connParam['delay'])  # if delay is a list, copy to delayList
        
        orderedPreGids = sorted(preCellsTags.keys())
        orderedPostGids = sorted(postCellsTags.keys())
        for iconn, (relativePreId, relativePostId) in enumerate(connParam['connList']):  # for each postsyn cell
            preCellGid = orderedPreGids[relativePreId]
            preCellTags = preCellsTags[preCellGid]  # get pre cell based on relative id        
            postCellGid = orderedPostGids[relativePostId]
            if postCellGid in f.net.lid2gid:  # check if postsyn is in this node's list of gids
                postCell = f.net.cells[f.net.gid2lid[postCellGid]]  # get Cell object 
                if 'weightFromList' in connParam: connParam['weight'] = connParam['weightFromList'][iconn] 
                if 'delayFromList' in connParam: connParam['delay'] = connParam['delayFromList'][iconn]
                if preCellTags['cellModel'] == 'NetStim':  # if NetStim
                    if preCellTags['cellModel'] == 'NetStim':  # if NetStim
                        self._addCellNetStim(connParam, preCellTags, preCellGid, postCellGid) # cell method to add connection               
                    elif preCellGid != postCellGid: # if not self-connection
                        self._addCellConn(connParam, preCellGid, postCellGid) # add connection


    ###############################################################################
    ### Set parameters and create NetStim and connection
    ###############################################################################
    def _addCellNetStim(self, connParam, preCellTags, preCellGid, postCellGid):
        # set weight
        if 'weightList' in connParam:
            weight = connParam['weightList'][preCellGid,postCellGid]
        elif 'weightFunc' in connParam:
            weight = connParam['weightFunc'](**connParam['weightFuncArgs']) 
        else:
            weight = connParam['weight']
        
        # set delay
        if 'delayList' in connParam:
            delay = connParam['delayList'][preCellGid,postCellGid]
        elif 'delayFunc' in connParam:
            delay = connParam['delayFunc'](**connParam['delayFuncArgs']) 
        else:
            delay = connParam['delay']
        
        # get Cell object 
        postCell = f.net.cells[f.net.gid2lid[postCellGid]] 

        # convert synMech param to list (if not already)
        if not isinstance(connParam['synMech'], list):
            connParam['synMech'] = [connParam['synMech']]

        # generate dict with final params
        for i, synMech in enumerate(connParam['synMech']):
            if 'synWeightFraction' in connParam: # adapt weight for each synMech
                weight = weight * connParam['synMechWeightFactor'][i]

            params = {'popLabel': preCellTags['popLabel'],
            'rate': preCellTags['rate'],
            'noise': preCellTags['noise'],
            'source': preCellTags['source'], 
            'number': preCellTags['number'],
            'start': preCellTags['start'],
            'sec': connParam['sec'], 
            'synMech': synMech,
            'weight': weight,
            'delay': delay,
            'threshold': connParam['threshold'],
            'seed': preCellTags['seed'] if 'seed' in preCellTags else f.cfg['seeds']['stim']}

            postCell.addNetStim(params)  # call cell method to add connections 


    ###############################################################################
    ### Set parameters and create connection
    ###############################################################################
    def _addCellConn(self, connParam, preCellGid, postCellGid):
        # set weight
        if 'weightList' in connParam:
            weight = connParam['weightList'][preCellGid,postCellGid]
        elif 'weightFunc' in connParam:
            weight = connParam['weightFunc'](**connParam['weightFuncArgs']) 
        else:
            weight = connParam['weight']
        
        # set delay
        if 'delayList' in connParam:
            delay = connParam['delayList'][preCellGid,postCellGid]
        elif 'delayFunc' in connParam:
            delay = connParam['delayFunc'](**connParam['delayFuncArgs']) 
        else:
            delay = connParam['delay']

        # get Cell object 
        postCell = f.net.cells[f.net.gid2lid[postCellGid]] 

        # convert synMech param to list (if not already)
        if not isinstance(connParam['synMech'], list):
            connParam['synMech'] = [connParam['synMech']]

        # generate dict with final params
        for i, synMech in enumerate(connParam['synMech']):
            if 'synWeightFraction' in connParam: # adapt weight for each synMech
                weight = weight * connParam['synMechWeightFactor'][i]

            params = {'preGid': preCellGid, 
            'sec': connParam['sec'], 
            'synMech': synMech, 
            'weight': weight,
            'delay': delay,
            'threshold': connParam['threshold'],
            'plasticity': connParam.get('plasticity')}
            
            postCell.addConn(params)