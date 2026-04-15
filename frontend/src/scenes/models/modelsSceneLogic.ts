import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { DataModelingNode } from '~/types'

import type { modelsSceneLogicType } from './modelsSceneLogicType'

export const modelsSceneLogic = kea<modelsSceneLogicType>([
    path(['scenes', 'models', 'modelsSceneLogic']),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading']],
        actions: [dataWarehouseViewsLogic, ['loadDataWarehouseSavedQueries']],
    })),
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
    afterMount(({ actions }) => {
        actions.loadDataWarehouseSavedQueries()
        actions.loadNodes()
    }),
])
