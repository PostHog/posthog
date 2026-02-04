import { afterMount, connect, kea, path } from 'kea'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import type { modelsSceneLogicType } from './modelsSceneLogicType'

export const modelsSceneLogic = kea<modelsSceneLogicType>([
    path(['scenes', 'models', 'modelsSceneLogic']),
    connect(() => ({
        values: [dataWarehouseViewsLogic, ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueriesLoading']],
        actions: [dataWarehouseViewsLogic, ['loadDataWarehouseSavedQueries']],
    })),
    afterMount(({ actions }) => {
        actions.loadDataWarehouseSavedQueries()
    }),
])
