import { MakeLogicType, afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataModelingEdge, DataModelingNode } from '~/types'

export interface lineageDataLogicValues {
    nodes: DataModelingNode[]
    nodesLoading: boolean
    edges: DataModelingEdge[]
    edgesLoading: boolean
}

export interface lineageDataLogicActions {
    loadNodes: () => any
    loadNodesSuccess: (nodes: DataModelingNode[], payload?: any) => { nodes: DataModelingNode[]; payload?: any }
    loadNodesFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadEdges: () => any
    loadEdgesSuccess: (edges: DataModelingEdge[], payload?: any) => { edges: DataModelingEdge[]; payload?: any }
    loadEdgesFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
}

export type lineageDataLogicType = MakeLogicType<lineageDataLogicValues, lineageDataLogicActions>

/**
 * The team's DAG, loaded once. The models table, the lineage canvas and the models scene all read it,
 * so it cannot live on any one of them: whichever mounts first would then fetch for the others.
 */
export const lineageDataLogic = kea<lineageDataLogicType>([
    path(['products', 'data_modeling', 'frontend', 'lineage', 'lineageDataLogic']),
    loaders({
        nodes: {
            __default: [] as DataModelingNode[],
            loadNodes: async () => {
                const response = await api.dataModelingNodes.list()
                return response.results
            },
        },
        edges: {
            __default: [] as DataModelingEdge[],
            loadEdges: async () => {
                const response = await api.dataModelingEdges.list()
                return response.results
            },
        },
    }),
    afterMount(({ actions }) => {
        actions.loadNodes()
        actions.loadEdges()
    }),
])
