import { connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { DatabaseSchemaViewTable } from '~/queries/schema'
import { ProductKey } from '~/types'

import type { dataWarehouseViewsLogicType } from './dataWarehouseViewsLogicType'

export const dataWarehouseViewsLogic = kea<dataWarehouseViewsLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSavedQueriesLogic']),
    connect(() => ({
        values: [userLogic, ['user'], databaseTableListLogic, ['views', 'databaseLoading']],
        actions: [databaseTableListLogic, ['loadDatabase']],
    })),

    loaders({
        dataWarehouseSavedQueries: [
            null,
            {
                createDataWarehouseSavedQuery: async (view: Partial<DatabaseSchemaViewTable>) => {
                    await api.dataWarehouseSavedQueries.create(view)
                    return null
                },
                deleteDataWarehouseSavedQuery: async (viewId: string) => {
                    await api.dataWarehouseSavedQueries.delete(viewId)
                    return null
                },
                updateDataWarehouseSavedQuery: async (view: DatabaseSchemaViewTable) => {
                    await api.dataWarehouseSavedQueries.update(view.id, view)
                    return null
                },
            },
        ],
    }),
    listeners(({ actions }) => ({
        createDataWarehouseSavedQuerySuccess: () => {
            actions.loadDatabase()
            router.actions.push(urls.dataWarehouse())
        },
        updateDataWarehouseSavedQuerySuccess: () => {
            actions.loadDatabase()
        },
    })),
    selectors({
        shouldShowEmptyState: [
            (s) => [s.views, s.databaseLoading],
            (views, databaseLoading): boolean => {
                return views?.length == 0 && !databaseLoading
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.DATA_WAREHOUSE_SAVED_QUERY]
            },
        ],
    }),
])
