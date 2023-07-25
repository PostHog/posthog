import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { DataWarehouseView, ProductKey } from '~/types'
import { userLogic } from 'scenes/userLogic'

import type { dataWarehouseViewsLogicType } from './dataWarehouseViewsLogicType'
import { DataWarehouseSceneRow } from '../types'

export const dataWarehouseViewsLogic = kea<dataWarehouseViewsLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseViewsLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),

    loaders(({ values }) => ({
        dataWarehouseViews: [
            null as PaginatedResponse<DataWarehouseView> | null,
            {
                loadDataWarehouseViews: async () => await api.dataWarehouseViews.list(),
                createDataWarehouseView: async (view: Partial<DataWarehouseView>) => {
                    const newView = await api.dataWarehouseViews.create(view)
                    return {
                        ...values.dataWarehouseViews,
                        results: values.dataWarehouseViews
                            ? [...values.dataWarehouseViews.results, newView]
                            : [newView],
                    }
                },
            },
        ],
    })),
    selectors({
        views: [
            (s) => [s.dataWarehouseViews],
            (warehouseViews): DataWarehouseSceneRow[] => {
                if (!warehouseViews) {
                    return []
                }

                return warehouseViews.results.map(
                    (view: DataWarehouseView) =>
                        ({
                            id: view.id,
                            name: view.name,
                            columns: view.columns,
                            query: view.query,
                        } as DataWarehouseSceneRow)
                )
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.views, s.dataWarehouseViewsLoading],
            (views, dataWarehouseViewsLoading): boolean => {
                return views?.length == 0 && !dataWarehouseViewsLoading
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.DATA_WAREHOUSE_VIEWS]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDataWarehouseViews()
    }),
])
