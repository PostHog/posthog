import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTableListRow } from 'scenes/data-warehouse/types'

import { query } from '~/queries/query'
import { DatabaseSchemaQuery, NodeKind } from '~/queries/schema'
import { DataWarehouseTable } from '~/types'

import type { databaseTableListLogicType } from './databaseTableListLogicType'

export const databaseTableListLogic = kea<databaseTableListLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseTableListLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    loaders(({ values }) => ({
        database: [
            null as Required<DatabaseSchemaQuery['response']> | null,
            {
                loadDatabase: async (): Promise<Required<DatabaseSchemaQuery['response']> | null> =>
                    await query({ kind: NodeKind.DatabaseSchemaQuery } as DatabaseSchemaQuery),
            },
        ],
        dataWarehouse: [
            null as PaginatedResponse<DataWarehouseTable> | null,
            {
                loadDataWarehouse: async (): Promise<PaginatedResponse<DataWarehouseTable>> =>
                    await api.dataWarehouseTables.list(),
                deleteDataWarehouseTable: async (table: DataWarehouseTable) => {
                    await api.dataWarehouseTables.delete(table.id)
                    return {
                        results: [...(values.dataWarehouse?.results || []).filter((t) => t.id != table.id)],
                    }
                },
            },
        ],
    })),
    reducers({ searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }] }),
    selectors({
        filteredTables: [
            (s) => [s.database, s.searchTerm],
            (database, searchTerm): DatabaseTableListRow[] => {
                if (!database) {
                    return []
                }

                return Object.entries(database)
                    .map(
                        ([key, value]) =>
                            ({
                                name: key,
                                columns: value,
                            } as DatabaseTableListRow)
                    )
                    .filter(({ name }) => name.toLowerCase().includes(searchTerm.toLowerCase()))
                    .sort((a, b) => a.name.localeCompare(b.name))
            },
        ],
        tableOptions: [
            (s) => [s.filteredTables],
            (filteredTables: DatabaseTableListRow[]) =>
                filteredTables.map((row) => ({
                    value: row.name,
                    label: row.name,
                    columns: row.columns,
                })),
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
            actions.loadDatabase()
        }
    }),
])
