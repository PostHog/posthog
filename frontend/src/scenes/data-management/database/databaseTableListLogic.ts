import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { objectsEqual } from 'lib/utils'

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

const toMapByName = <T extends { name: string }>(items: T[]): Record<string, T> =>
    items.reduce(
        (acc, cur) => {
            acc[cur.name] = cur
            return acc
        },
        {} as Record<string, T>
    )

const toMapById = <T extends { id: string }>(items: T[]): Record<string, T> =>
    items.reduce(
        (acc, cur) => {
            acc[cur.id] = cur
            return acc
        },
        {} as Record<string, T>
    )

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
            (s) => [s.allTables, s.searchTerm],
            (allTables, searchTerm): DatabaseSchemaTable[] => {
                return allTables
                    .filter(({ name }) => name.toLowerCase().includes(searchTerm.toLowerCase()))
                    .sort((a, b) => a.name.localeCompare(b.name))
            },
            { resultEqualityCheck: objectsEqual },
        ],
        allTables: [
            (s) => [s.database],
            (database): DatabaseSchemaTable[] => {
                if (!database || !database.tables) {
                    return []
                }

                return Object.values(database.tables)
            },
            { resultEqualityCheck: objectsEqual },
        ],
        allTablesMap: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): Record<string, DatabaseSchemaTable> => toMapByName(allTables),
            { resultEqualityCheck: objectsEqual },
        ],
        posthogTables: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaTable[] => {
                return allTables.filter((n) => n.type === 'posthog')
            },
            { resultEqualityCheck: objectsEqual },
        ],
        posthogTablesMap: [
            (s) => [s.posthogTables],
            (posthogTables: DatabaseSchemaTable[]): Record<string, DatabaseSchemaTable> => toMapByName(posthogTables),
            { resultEqualityCheck: objectsEqual },
        ],
        systemTables: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaTable[] => {
                return allTables.filter((n) => n.type === 'system')
            },
            { resultEqualityCheck: objectsEqual },
        ],
        systemTablesMap: [
            (s) => [s.systemTables],
            (systemTables: DatabaseSchemaTable[]): Record<string, DatabaseSchemaTable> => toMapByName(systemTables),
            { resultEqualityCheck: objectsEqual },
        ],
        dataWarehouseTables: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaDataWarehouseTable[] => {
                return allTables.filter((n): n is DatabaseSchemaDataWarehouseTable => n.type === 'data_warehouse')
            },
            { resultEqualityCheck: objectsEqual },
        ],
        dataWarehouseTablesMap: [
            (s) => [s.dataWarehouseTables, s.views],
            (
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                views: DatabaseSchemaViewTable[]
            ): Record<string, DatabaseSchemaDataWarehouseTable | DatabaseSchemaViewTable> =>
                toMapByName([...dataWarehouseTables, ...views]),
            { resultEqualityCheck: objectsEqual },
        ],
        dataWarehouseTablesMapById: [
            (s) => [s.dataWarehouseTables, s.views],
            (
                dataWarehouseTables: DatabaseSchemaDataWarehouseTable[],
                views: DatabaseSchemaViewTable[]
            ): Record<string, DatabaseSchemaDataWarehouseTable | DatabaseSchemaViewTable> =>
                toMapById([...dataWarehouseTables, ...views]),
            { resultEqualityCheck: objectsEqual },
        ],
        views: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaViewTable[] => {
                return allTables.filter((n): n is DatabaseSchemaViewTable => n.type === 'view')
            },
            { resultEqualityCheck: objectsEqual },
        ],
        managedViews: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaManagedViewTable[] => {
                return allTables.filter((n): n is DatabaseSchemaManagedViewTable => n.type === 'managed_view')
            },
            { resultEqualityCheck: objectsEqual },
        ],
        viewsMap: [
            (s) => [s.views, s.managedViews],
            (
                views: DatabaseSchemaViewTable[],
                managedViews: DatabaseSchemaManagedViewTable[]
            ): Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable> =>
                toMapByName([...views, ...managedViews]),
            { resultEqualityCheck: objectsEqual },
        ],
        viewsMapById: [
            (s) => [s.views, s.managedViews],
            (
                views: DatabaseSchemaViewTable[],
                managedViews: DatabaseSchemaManagedViewTable[]
            ): Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable> =>
                toMapById([...views, ...managedViews]),
            { resultEqualityCheck: objectsEqual },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
    }),
])
