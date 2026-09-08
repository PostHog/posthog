import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { modelsSceneLogic } from './modelsSceneLogic'

export interface modelsGraphLogicValues {
    nodes: DataModelingNode[] // modelsSceneLogic
    nodesLoading: boolean // modelsSceneLogic
    searchTerm: string
    edges: DataModelingEdge[]
    edgesLoading: boolean
    highlightedNodeIds: Set<string>
}

export interface modelsGraphLogicActions {
    setSearchTerm: (searchTerm: string) => { searchTerm: string }
    loadEdges: () => any
    loadEdgesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadEdgesSuccess: (
        edges: DataModelingEdge[],
        payload?: any
    ) => {
        edges: DataModelingEdge[]
        payload?: any
    }
}

export interface modelsGraphLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        highlightedNodeIds: (nodes: DataModelingNode[], searchTerm: string) => Set<string>
    }
}

export type modelsGraphLogicType = MakeLogicType<
    modelsGraphLogicValues,
    modelsGraphLogicActions,
    Record<string, any>,
    modelsGraphLogicMeta
>

export const modelsGraphLogic = kea<modelsGraphLogicType>([
    path(['scenes', 'models', 'modelsGraphLogic']),
    connect(() => ({
        values: [modelsSceneLogic, ['nodes', 'nodesLoading']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    loaders({
        edges: {
            __default: [] as DataModelingEdge[],
            loadEdges: async () => {
                const response = await api.dataModelingEdges.list()
                return response.results
            },
        },
    }),
    selectors({
        highlightedNodeIds: [
            (s) => [s.nodes, s.searchTerm],
            (nodes: DataModelingNode[], searchTerm: string): Set<string> => {
                const term = searchTerm.trim().toLowerCase()
                if (!term) {
                    return new Set()
                }
                return new Set(nodes.filter((node) => node.name.toLowerCase().includes(term)).map((node) => node.id))
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEdges()
    }),
])
