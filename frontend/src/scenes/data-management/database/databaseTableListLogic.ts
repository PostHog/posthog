import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaTable,
    DatabaseSchemaViewTable,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

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
                    await performQuery(
                        setLatestVersionsOnQuery({ kind: NodeKind.DatabaseSchemaQuery }) as DatabaseSchemaQuery
                    ),
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
        managedViews: [
            (s) => [s.database],
            (database): DatabaseSchemaManagedViewTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables).filter(
                    (n): n is DatabaseSchemaManagedViewTable => n.type === 'managed_view'
                )
            },
        ],
        viewsMap: [
            (s) => [s.database, s.views, s.managedViews],
            (
                database,
                views,
                managedViews
            ): Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable> => {
                if (!database?.tables) {
                    return {}
                }

                return [...views, ...managedViews].reduce((acc, cur) => {
                    acc[cur.name] = database.tables[cur.name] as
                        | DatabaseSchemaViewTable
                        | DatabaseSchemaManagedViewTable
                    return acc
                }, {} as Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable>)
            },
        ],
        viewsMapById: [
            (s) => [s.viewsMap],
            (viewsMap): Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable> => {
                return Object.values(viewsMap).reduce((acc, cur) => {
                    acc[cur.id] = cur
                    return acc
                }, {} as Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable>)
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
    }),
])
