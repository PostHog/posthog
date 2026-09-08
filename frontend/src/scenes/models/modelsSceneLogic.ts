import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

import type { DataWarehouseSavedQuery } from '../../types'

export type ModelsSceneTab = 'models' | 'runs' | 'graph'

const MODELS_SCENE_TABS: ModelsSceneTab[] = ['models', 'runs', 'graph']

function isModelsSceneTab(tab: unknown): tab is ModelsSceneTab {
    return typeof tab === 'string' && (MODELS_SCENE_TABS as string[]).includes(tab)
}

export interface modelsSceneLogicValues {
    dataWarehouseSavedQueries: DataWarehouseSavedQuery[] // dataWarehouseViewsLogic
    dataWarehouseSavedQueriesLoading: boolean // dataWarehouseViewsLogic
    activeTab: ModelsSceneTab
    nodes: DataModelingNode[]
    nodesLoading: boolean
    savedQueryIdToNodeId: Record<string, string>
    failingNodes: DataModelingNode[]
    suspendedViews: DataWarehouseSavedQuery[]
}

export interface modelsSceneLogicActions {
    loadDataWarehouseSavedQueries: () => any // dataWarehouseViewsLogic
    setActiveTab: (tab: ModelsSceneTab) => { tab: ModelsSceneTab }
    loadNodes: () => any
    loadNodesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadNodesSuccess: (
        nodes: DataModelingNode[],
        payload?: any
    ) => {
        nodes: DataModelingNode[]
        payload?: any
    }
}

export interface modelsSceneLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        savedQueryIdToNodeId: (nodes: DataModelingNode[]) => Record<string, string>
        failingNodes: (nodes: DataModelingNode[]) => DataModelingNode[]
        suspendedViews: (dataWarehouseSavedQueries: DataWarehouseSavedQuery[]) => DataWarehouseSavedQuery[]
    }
}

export type modelsSceneLogicType = MakeLogicType<
    modelsSceneLogicValues,
    modelsSceneLogicActions,
    Record<string, any>,
    modelsSceneLogicMeta
>

export const modelsSceneLogic = kea<modelsSceneLogicType>([
    path(['scenes', 'models', 'modelsSceneLogic']),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading']],
        actions: [dataWarehouseViewsLogic, ['loadDataWarehouseSavedQueries']],
    })),
    actions({
        setActiveTab: (tab: ModelsSceneTab) => ({ tab }),
    }),
    reducers({
        activeTab: [
            'models' as ModelsSceneTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    loaders({
        nodes: {
            __default: [] as DataModelingNode[],
            loadNodes: async () => {
                const response = await api.dataModelingNodes.list()
                return response.results
            },
        },
    }),
    selectors({
        savedQueryIdToNodeId: [
            (s) => [s.nodes],
            (nodes: DataModelingNode[]): Record<string, string> => {
                const map: Record<string, string> = {}
                for (const node of nodes) {
                    if (node.saved_query_id) {
                        map[node.saved_query_id] = node.id
                    }
                }
                return map
            },
        ],
        failingNodes: [
            (s) => [s.nodes],
            (nodes: DataModelingNode[]): DataModelingNode[] =>
                nodes.filter((node) => node.last_run_status === 'Failed'),
        ],
        suspendedViews: [
            (s) => [s.dataWarehouseSavedQueries],
            (dataWarehouseSavedQueries: DataWarehouseSavedQuery[]): DataWarehouseSavedQuery[] =>
                dataWarehouseSavedQueries.filter((view) => Object.keys(view.suspended ?? {}).length > 0),
        ],
    }),
    urlToAction(({ actions, values }) => ({
        [urls.models()]: (_, searchParams) => {
            const tab = isModelsSceneTab(searchParams.tab) ? searchParams.tab : 'models'
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataWarehouseSavedQueries()
        actions.loadNodes()
    }),
])
