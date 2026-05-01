import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { objectsEqual } from 'lib/utils'

import { performQuery } from '~/queries/query'
import {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaEndpointTable,
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

let inFlightDatabaseLoadKey: string | null = null
let inFlightDatabaseLoadPromise: Promise<Required<DatabaseSchemaQueryResponse> | null> | null = null

export const databaseTableListLogic = kea<databaseTableListLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseTableListLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setConnection: (connectionId: string | null) => ({ connectionId }),
    }),
    loaders(({ values }) => ({
        database: [
            null as Required<DatabaseSchemaQueryResponse> | null,
            {
                loadDatabase: async (): Promise<Required<DatabaseSchemaQueryResponse> | null> => {
                    const requestConnectionId = values.connectionId ?? undefined
                    const requestKey = requestConnectionId ?? '__posthog__'

                    if (inFlightDatabaseLoadKey === requestKey && inFlightDatabaseLoadPromise) {
                        return await inFlightDatabaseLoadPromise
                    }

                    const request = performQuery(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.DatabaseSchemaQuery,
                            connectionId: requestConnectionId,
                        }) as DatabaseSchemaQuery
                    )

                    inFlightDatabaseLoadKey = requestKey
                    inFlightDatabaseLoadPromise = request

                    try {
                        const database = await request
                        const currentConnectionId = values.connectionId ?? undefined

                        if (currentConnectionId !== requestConnectionId) {
                            return values.database
                        }

                        return database
                    } finally {
                        if (inFlightDatabaseLoadKey === requestKey) {
                            inFlightDatabaseLoadKey = null
                            inFlightDatabaseLoadPromise = null
                        }
                    }
                },
            },
        ],
    })),
    reducers({
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        connectionId: [null as string | null, { setConnection: (_, { connectionId }) => connectionId }],
    }),
    selectors({
        allPosthogTables: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaTable[] => {
                return allTables.filter((n) => n.type === 'posthog')
            },
            { resultEqualityCheck: objectsEqual },
        ],
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
            (s) => [s.database, s.databaseLoading],
            (database, databaseLoading): DatabaseSchemaTable[] => {
                if (databaseLoading || !database || !database.tables) {
                    return []
                }

                return Object.values(database.tables)
            },
            { resultEqualityCheck: objectsEqual },
        ],
        allTablesMap: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): Record<string, DatabaseSchemaTable> =>
                toMapByName(allTables.filter((t) => t.type !== 'endpoint')),
            { resultEqualityCheck: objectsEqual },
        ],
        posthogTables: [
            (s) => [s.allPosthogTables, s.connectionId],
            (allPosthogTables: DatabaseSchemaTable[], connectionId: string | null): DatabaseSchemaTable[] => {
                if (connectionId) {
                    return []
                }
                const visiblePosthogTableNames = new Set(['events', 'groups', 'persons', 'sessions'])
                return allPosthogTables.filter((table) => visiblePosthogTableNames.has(table.name))
            },
            { resultEqualityCheck: objectsEqual },
        ],
        posthogTablesMap: [
            (s) => [s.posthogTables],
            (posthogTables: DatabaseSchemaTable[]): Record<string, DatabaseSchemaTable> => toMapByName(posthogTables),
            { resultEqualityCheck: objectsEqual },
        ],
        systemTables: [
            (s) => [s.allTables, s.connectionId],
            (allTables: DatabaseSchemaTable[], connectionId: string | null): DatabaseSchemaTable[] => {
                if (connectionId) {
                    return []
                }
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
        endpointTables: [
            (s) => [s.allTables],
            (allTables: DatabaseSchemaTable[]): DatabaseSchemaEndpointTable[] => {
                return allTables.filter((n): n is DatabaseSchemaEndpointTable => n.type === 'endpoint')
            },
            { resultEqualityCheck: objectsEqual },
        ],
        latestEndpointTables: [
            (s) => [s.endpointTables],
            (endpointTables: DatabaseSchemaEndpointTable[]): DatabaseSchemaEndpointTable[] => {
                const grouped: Record<string, DatabaseSchemaEndpointTable> = {}
                for (const table of endpointTables) {
                    const match = table.name.match(/^(.+)_v(\d+)$/)
                    if (!match) {
                        continue
                    }
                    const [, baseName, versionStr] = match
                    const version = parseInt(versionStr, 10)
                    const existing = grouped[baseName]
                    if (!existing) {
                        grouped[baseName] = table
                    } else {
                        const existingMatch = existing.name.match(/_v(\d+)$/)
                        const existingVersion = existingMatch ? parseInt(existingMatch[1], 10) : 0
                        if (version > existingVersion) {
                            grouped[baseName] = table
                        }
                    }
                }
                return Object.values(grouped)
            },
            { resultEqualityCheck: objectsEqual },
        ],
        viewsMap: [
            (s) => [s.views, s.managedViews, s.endpointTables],
            (
                views: DatabaseSchemaViewTable[],
                managedViews: DatabaseSchemaManagedViewTable[],
                endpointTables: DatabaseSchemaEndpointTable[]
            ): Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable | DatabaseSchemaEndpointTable> =>
                toMapByName([...views, ...managedViews, ...endpointTables]),
            { resultEqualityCheck: objectsEqual },
        ],
        viewsMapById: [
            (s) => [s.views, s.managedViews, s.endpointTables],
            (
                views: DatabaseSchemaViewTable[],
                managedViews: DatabaseSchemaManagedViewTable[],
                endpointTables: DatabaseSchemaEndpointTable[]
            ): Record<string, DatabaseSchemaViewTable | DatabaseSchemaManagedViewTable | DatabaseSchemaEndpointTable> =>
                toMapById([...views, ...managedViews, ...endpointTables]),
            { resultEqualityCheck: objectsEqual },
        ],
    }),
])
