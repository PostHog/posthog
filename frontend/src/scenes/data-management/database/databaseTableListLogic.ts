import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { objectsEqual } from 'lib/utils/objects'

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

// Monotonic epoch advanced only when a load issues a fresh request. A newer load (e.g. one
// triggered by a schema mutation via refreshDatabaseSchema) supersedes older in-flight ones, so a
// slow or out-of-order response can never overwrite a fresher schema. Piggybacking loads adopt the
// in-flight request's epoch rather than advancing it, so they never make the original fetcher look
// superseded.
let latestDatabaseLoadEpoch = 0
let inFlightDatabaseLoadEpoch = 0

export const databaseTableListLogic = kea<databaseTableListLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseTableListLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setConnection: (connectionId: string | null) => ({ connectionId }),
        refreshDatabaseSchema: true,
    }),
    loaders(({ values }) => ({
        database: [
            null as Required<DatabaseSchemaQueryResponse> | null,
            {
                loadDatabase: async ({
                    force,
                }: { force?: boolean } = {}): Promise<Required<DatabaseSchemaQueryResponse> | null> => {
                    const requestConnectionId = values.connectionId ?? undefined
                    const requestKey = requestConnectionId ?? '__posthog__'

                    // Non-forced loads may piggyback on an identical in-flight request and adopt its
                    // epoch (they don't start a new generation). A forced refresh always issues a
                    // fresh request so it can never return pre-mutation data (and never waits on a
                    // hung stale request).
                    if (!force && inFlightDatabaseLoadKey === requestKey && inFlightDatabaseLoadPromise) {
                        const epoch = inFlightDatabaseLoadEpoch
                        const result = await inFlightDatabaseLoadPromise
                        // Reading `values` post-unmount throws kea's path-not-found error.
                        if (!databaseTableListLogic.isMounted()) {
                            return null
                        }
                        if (epoch !== latestDatabaseLoadEpoch) {
                            return values.database
                        }
                        return result
                    }

                    const epoch = ++latestDatabaseLoadEpoch
                    const request = performQuery(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.DatabaseSchemaQuery,
                            connectionId: requestConnectionId,
                        }) as DatabaseSchemaQuery
                    )

                    inFlightDatabaseLoadKey = requestKey
                    inFlightDatabaseLoadPromise = request
                    inFlightDatabaseLoadEpoch = epoch

                    let database: Required<DatabaseSchemaQueryResponse> | null = null
                    try {
                        database = await request
                    } finally {
                        // Identity check, not key equality: a concurrent forced refresh may have
                        // replaced the in-flight slot with its own request under the same key.
                        if (inFlightDatabaseLoadPromise === request) {
                            inFlightDatabaseLoadKey = null
                            inFlightDatabaseLoadPromise = null
                        }
                    }

                    // Reading `values` post-unmount throws kea's path-not-found error.
                    if (!databaseTableListLogic.isMounted()) {
                        return null
                    }

                    // A newer load or refresh started after us: discard this possibly-stale response
                    // rather than clobbering the fresher schema.
                    if (epoch !== latestDatabaseLoadEpoch) {
                        return values.database
                    }

                    const currentConnectionId = values.connectionId ?? undefined
                    if (currentConnectionId !== requestConnectionId) {
                        return values.database
                    }

                    return database
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
        // Tables synced from an external data source (Stripe, Postgres, etc). Excludes views/saved
        // queries and self-managed S3 tables — only these can trigger CDP from a warehouse sync.
        externalDataSourceTables: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]): DatabaseSchemaDataWarehouseTable[] => {
                return dataWarehouseTables.filter((table) => table.source != null)
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
    listeners(({ actions }) => ({
        refreshDatabaseSchema: () => {
            actions.loadDatabase({ force: true })
        },
    })),
])
