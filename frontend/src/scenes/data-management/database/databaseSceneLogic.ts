import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import type { databaseSceneLogicType } from './databaseSceneLogicType'
import { DatabaseSchemaQuery, NodeKind } from '~/queries/schema'
import api from 'lib/api'
import { DataBeachTableType } from '~/types'

export const databaseSceneLogic = kea<databaseSceneLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseSceneLogic']),
    actions({
        showAddDataBeachTable: true,
        hideAddDataBeachTable: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        toggleExpandedTable: (tableName: string) => ({ tableName }),
    }),
    reducers({
        addingDataBeachTable: [false, { showAddDataBeachTable: () => true, hideAddDataBeachTable: () => false }],
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        expandedTables: [
            {} as Record<string, boolean>,
            { toggleExpandedTable: (state, { tableName }) => ({ ...state, [tableName]: !state[tableName] }) },
        ],
    }),
    loaders({
        database: [
            null as Required<DatabaseSchemaQuery['response']> | null,
            {
                loadDatabase: async (): Promise<Required<DatabaseSchemaQuery['response']> | null> =>
                    await query({ kind: NodeKind.DatabaseSchemaQuery } as DatabaseSchemaQuery),
            },
        ],
        dataBeachTables: [
            null as DataBeachTableType[] | null,
            {
                loadDataBeachTables: async () => (await api.dataBeachTables.list())?.results,
            },
        ],
    }),
    selectors({
        filteredDatabase: [
            (s) => [s.database, s.searchTerm],
            (database, searchTerm): Required<DatabaseSchemaQuery['response']> | null => {
                if (!database) {
                    return null
                }
                if (!searchTerm) {
                    return database
                }
                return (
                    Object.fromEntries(
                        Object.entries(database).filter(([key]) => key.toLowerCase().includes(searchTerm.toLowerCase()))
                    ) ?? null
                )
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
        actions.loadDataBeachTables()
    }),
])
