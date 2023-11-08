import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import { DatabaseSchemaQuery, DatabaseSchemaQueryResponseField, NodeKind } from '~/queries/schema'

import type { databaseTableListLogicType } from './databaseTableListLogicType'

export interface DatabaseTableListRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
}

export const databaseTableListLogic = kea<databaseTableListLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseTableListLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders({
        database: [
            null as Required<DatabaseSchemaQuery['response']> | null,
            {
                loadDatabase: async (): Promise<Required<DatabaseSchemaQuery['response']> | null> =>
                    await query({ kind: NodeKind.DatabaseSchemaQuery } as DatabaseSchemaQuery),
            },
        ],
    }),
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
                })),
        ],
    }),
    afterMount(({ actions }) => actions.loadDatabase()),
])
