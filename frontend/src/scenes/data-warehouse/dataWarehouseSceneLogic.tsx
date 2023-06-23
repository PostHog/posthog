import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { DatabaseSchemaQueryResponseField } from '~/queries/schema'
import { DataWarehouseTable, ProductKey } from '~/types'
import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'
import { userLogic } from 'scenes/userLogic'

export interface DatabaseSceneRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
}

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    loaders({
        dataWarehouse: [
            null as PaginatedResponse<DataWarehouseTable> | null,
            {
                loadDataWarehouse: async (): Promise<PaginatedResponse<DataWarehouseTable>> =>
                    await api.dataWarehouseTables.list(),
            },
        ],
    }),
    selectors({
        tables: [
            (s) => [s.dataWarehouse],
            (warehouse): DatabaseSceneRow[] => {
                if (!warehouse) {
                    return []
                }

                return warehouse.results.map(
                    (table: DataWarehouseTable) =>
                        ({
                            name: table.name,
                            columns: table.columns,
                        } as DatabaseSceneRow)
                )
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.tables, s.dataWarehouseLoading],
            (tables, dataWarehouseLoading): boolean => {
                return tables?.length == 0 && !dataWarehouseLoading
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.DATA_WAREHOUSE]
            },
        ],
    }),
    afterMount(({ actions }) => actions.loadDataWarehouse()),
])
