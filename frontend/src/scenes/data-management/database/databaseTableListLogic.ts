import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaTable,
    DatabaseSchemaViewTable,
    NodeKind,
} from '~/queries/schema'

import type { databaseTableListLogicType } from './databaseTableListLogicType'

export const databaseTableListLogic = kea<databaseTableListLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseTableListLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders({
        database: [
            null as Required<DatabaseSchemaQueryResponse> | null,
            {
                loadDatabase: async (): Promise<Required<DatabaseSchemaQueryResponse> | null> =>
                    await performQuery({ kind: NodeKind.DatabaseSchemaQuery } as DatabaseSchemaQuery),
            },
        ],
    }),
    reducers({ searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }] }),
    selectors({
        filteredTables: [
            (s) => [s.database, s.searchTerm],
            (database, searchTerm): DatabaseSchemaTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables)
                    .filter(({ name }) => name.toLowerCase().includes(searchTerm.toLowerCase()))
                    .sort((a, b) => a.name.localeCompare(b.name))
            },
        ],
        allTables: [
            (s) => [s.database],
            (database): DatabaseSchemaTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables)
            },
        ],
        allTablesMap: [
            (s) => [s.database],
            (database): Record<string, DatabaseSchemaTable> => {
                if (!database || !database.tables) {
                    return {}
                }

                return Object.values(database.tables).reduce((acc, cur) => {
                    acc[cur.name] = database.tables[cur.name]
                    return acc
                }, {} as Record<string, DatabaseSchemaTable>)
            },
        ],
        posthogTables: [
            (s) => [s.database],
            (database): DatabaseSchemaTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables).filter((n) => n.type === 'posthog')
            },
        ],
        posthogTablesMap: [
            (s) => [s.database],
            (database): Record<string, DatabaseSchemaTable> => {
                if (!database || !database.tables) {
                    return {}
                }

                return Object.values(database.tables)
                    .filter((n) => n.type === 'posthog')
                    .reduce((acc, cur) => {
                        acc[cur.name] = database.tables[cur.name]
                        return acc
                    }, {} as Record<string, DatabaseSchemaTable>)
            },
        ],
        dataWarehouseTables: [
            (s) => [s.database],
            (database): DatabaseSchemaDataWarehouseTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables).filter(
                    (n): n is DatabaseSchemaDataWarehouseTable => n.type === 'data_warehouse'
                )
            },
        ],
        dataWarehouseTablesMap: [
            (s) => [s.database],
            (database): Record<string, DatabaseSchemaDataWarehouseTable> => {
                if (!database || !database.tables) {
                    return {}
                }

                return Object.values(database.tables)
                    .filter(
                        (n): n is DatabaseSchemaDataWarehouseTable => n.type === 'data_warehouse' || n.type == 'view'
                    )
                    .reduce((acc, cur) => {
                        acc[cur.name] = database.tables[cur.name] as DatabaseSchemaDataWarehouseTable
                        return acc
                    }, {} as Record<string, DatabaseSchemaDataWarehouseTable>)
            },
        ],
        dataWarehouseTablesMapById: [
            (s) => [s.database],
            (database): Record<string, DatabaseSchemaDataWarehouseTable> => {
                if (!database || !database.tables) {
                    return {}
                }

                return Object.values(database.tables)
                    .filter(
                        (n): n is DatabaseSchemaDataWarehouseTable => n.type === 'data_warehouse' || n.type == 'view'
                    )
                    .reduce((acc, cur) => {
                        acc[cur.id] = database.tables[cur.name] as DatabaseSchemaDataWarehouseTable
                        return acc
                    }, {} as Record<string, DatabaseSchemaDataWarehouseTable>)
            },
        ],
        views: [
            (s) => [s.database],
            (database): DatabaseSchemaViewTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables).filter((n): n is DatabaseSchemaViewTable => n.type === 'view')
            },
        ],
        viewsMap: [
            (s) => [s.database],
            (database): Record<string, DatabaseSchemaViewTable> => {
                if (!database || !database.tables) {
                    return {}
                }

                return Object.values(database.tables)
                    .filter((n): n is DatabaseSchemaViewTable => n.type === 'view')
                    .reduce((acc, cur) => {
                        acc[cur.name] = database.tables[cur.name] as DatabaseSchemaViewTable
                        return acc
                    }, {} as Record<string, DatabaseSchemaViewTable>)
            },
        ],
        viewsMapById: [
            (s) => [s.database],
            (database): Record<string, DatabaseSchemaViewTable> => {
                if (!database || !database.tables) {
                    return {}
                }

                return Object.values(database.tables)
                    .filter((n): n is DatabaseSchemaViewTable => n.type === 'view')
                    .reduce((acc, cur) => {
                        acc[cur.id] = database.tables[cur.name] as DatabaseSchemaViewTable
                        return acc
                    }, {} as Record<string, DatabaseSchemaViewTable>)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
    }),
])
