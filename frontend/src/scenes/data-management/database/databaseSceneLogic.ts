import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import type { databaseSceneLogicType } from './databaseSceneLogicType'
import { DatabaseSchemaQuery, DatabaseSchemaQueryResponseField, NodeKind } from '~/queries/schema'

export interface DatabaseSceneRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
}

export const databaseSceneLogic = kea<databaseSceneLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseSceneLogic']),
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
            (database, searchTerm): DatabaseSceneRow[] => {
                if (!database) {
                    return []
                }

                return Object.entries(database)
                    .map(
                        ([key, value]) =>
                            ({
                                name: key,
                                columns: value,
                            } as DatabaseSceneRow)
                    )
                    .filter(({ name }) => name.toLowerCase().includes(searchTerm.toLowerCase()))
                    .sort((a, b) => a.name.localeCompare(b.name))
            },
        ],
        tableOptions: [
            (s) => [s.filteredTables],
            (filteredTables: DatabaseSceneRow[]) =>
                filteredTables.map((row) => ({
                    value: row.name,
                    label: row.name,
                })),
        ],
    }),
    afterMount(({ actions }) => actions.loadDatabase()),
])
