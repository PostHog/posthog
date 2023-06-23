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

export interface DataWarehouseSceneRow extends DatabaseSceneRow {
    id: string
    url_pattern: string
    format: string
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
            (warehouse): DataWarehouseSceneRow[] => {
                if (!warehouse) {
                    return []
                }

                return warehouse.results.map(
                    (table: DataWarehouseTable) =>
                        ({
                            id: table.id,
                            name: table.name,
                            columns: table.columns,
                            url_pattern: table.url_pattern,
                            format: table.format,
                        } as DataWarehouseSceneRow)
                )
            },
        ],
    }),
    afterMount(({ actions }) => actions.loadDataWarehouse()),
])
