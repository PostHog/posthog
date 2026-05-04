import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import api from 'lib/api'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

import type { modelsSceneLogicType } from './modelsSceneLogicType'

export const MODELS_SCENE_TABS = ['views', 'dags'] as const
export type ModelsSceneTab = (typeof MODELS_SCENE_TABS)[number]
export const DEFAULT_MODELS_SCENE_TAB: ModelsSceneTab = 'views'

export const modelsSceneLogic = kea<modelsSceneLogicType>([
    path(['scenes', 'models', 'modelsSceneLogic']),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading']],
        actions: [dataWarehouseViewsLogic, ['loadDataWarehouseSavedQueries']],
    })),
    actions({
        setCurrentTab: (tab: ModelsSceneTab) => ({ tab }),
        _setCurrentTab: (tab: ModelsSceneTab) => ({ tab }),
    }),
    reducers({
        currentTab: [
            DEFAULT_MODELS_SCENE_TAB as ModelsSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
                _setCurrentTab: (_, { tab }) => tab,
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
    }),
    actionToUrl(() => ({
        setCurrentTab: ({ tab }) => urls.models(tab === DEFAULT_MODELS_SCENE_TAB ? undefined : tab),
    })),
    urlToAction(({ actions, values }) => ({
        [urls.models()]: () => {
            if (values.currentTab !== DEFAULT_MODELS_SCENE_TAB) {
                actions._setCurrentTab(DEFAULT_MODELS_SCENE_TAB)
            }
        },
        [urls.models('dags')]: () => {
            if (values.currentTab !== 'dags') {
                actions._setCurrentTab('dags')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataWarehouseSavedQueries()
        actions.loadNodes()
    }),
])
