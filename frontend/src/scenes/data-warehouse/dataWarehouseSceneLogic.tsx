import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'

import { DatabaseSchemaQueryResponseField } from '~/queries/schema'
import { DataWarehouseTable } from '~/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

export interface DatabaseSceneRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
}

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSceneLogic']),
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
    }),
    afterMount(({ actions }) => actions.loadDataWarehouse()),
])
