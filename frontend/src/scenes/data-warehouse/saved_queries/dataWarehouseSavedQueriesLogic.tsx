import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { DataWarehouseSavedQuery, ProductKey } from '~/types'

import { DataWarehouseSceneRow } from '../types'
import type { dataWarehouseSavedQueriesLogicType } from './dataWarehouseSavedQueriesLogicType'

export const dataWarehouseSavedQueriesLogic = kea<dataWarehouseSavedQueriesLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSavedQueriesLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),

    loaders(({ values }) => ({
        dataWarehouseSavedQueries: [
            null as PaginatedResponse<DataWarehouseSavedQuery> | null,
            {
                loadDataWarehouseSavedQueries: async () => await api.dataWarehouseSavedQueries.list(),
                createDataWarehouseSavedQuery: async (view: Partial<DataWarehouseSavedQuery>) => {
                    const newView = await api.dataWarehouseSavedQueries.create(view)
                    return {
                        ...values.dataWarehouseSavedQueries,
                        results: values.dataWarehouseSavedQueries
                            ? [...values.dataWarehouseSavedQueries.results, newView]
                            : [newView],
                    }
                },
                deleteDataWarehouseSavedQuery: async (view: DataWarehouseSavedQuery) => {
                    await api.dataWarehouseSavedQueries.delete(view.id)
                    return {
                        ...values.dataWarehouseSavedQueries,
                        results: values.dataWarehouseSavedQueries
                            ? values.dataWarehouseSavedQueries.results.filter((v) => v.id !== view.id)
                            : [],
                    }
                },
            },
        ],
    })),
    listeners(() => ({
        createDataWarehouseSavedQuerySuccess: () => {
            router.actions.push(urls.dataWarehouse())
        },
    })),
    selectors({
        savedQueries: [
            (s) => [s.dataWarehouseSavedQueries],
            (warehouseSavedQueries): DataWarehouseSceneRow[] => {
                if (!warehouseSavedQueries) {
                    return []
                }

                return warehouseSavedQueries.results.map(
                    (savedQuery: DataWarehouseSavedQuery) =>
                        ({
                            id: savedQuery.id,
                            name: savedQuery.name,
                            columns: savedQuery.columns,
                            query: savedQuery.query,
                        } as DataWarehouseSceneRow)
                )
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.savedQueries, s.dataWarehouseSavedQueriesLoading],
            (savedQueries, dataWarehouseSavedQueriesLoading): boolean => {
                return savedQueries?.length == 0 && !dataWarehouseSavedQueriesLoading
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.DATA_WAREHOUSE_SAVED_QUERY]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDataWarehouseSavedQueries()
    }),
])
