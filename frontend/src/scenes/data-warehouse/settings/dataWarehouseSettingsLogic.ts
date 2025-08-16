import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'posthog-js'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import {
    externalDataSourcesLogic,
    UnifiedRecentActivity,
    DashboardDataSource,
} from 'scenes/data-warehouse/externalDataSourcesLogic'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'
import type { PaginatedResponse } from 'lib/api'
import { ExternalDataSchemaStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'

import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'

const REFRESH_INTERVAL = 10000

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables'],
            externalDataSourcesLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading', 'recentActivity'],
            availableSourcesDataLogic,
            ['availableSources'],
        ],
        actions: [
            databaseTableListLogic,
            ['loadDatabase'],
            externalDataSourcesLogic,
            ['loadSources', 'loadSourcesSuccess', 'updateSource'],
        ],
    })),
    actions({
        deleteSource: (source: ExternalDataSource) => ({ source }),
        reloadSource: (source: ExternalDataSource) => ({ source }),
        sourceLoadingFinished: (source: ExternalDataSource) => ({ source }),
        schemaLoadingFinished: (schema: ExternalDataSourceSchema) => ({ schema }),
        deleteSelfManagedTable: (tableId: string) => ({ tableId }),
        refreshSelfManagedTableSchema: (tableId: string) => ({ tableId }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ actions, values }) => ({
        schemas: [
            null,
            {
                updateSchema: async (schema: ExternalDataSourceSchema) => {
                    // Optimistic UI updates before sending updates to the backend
                    const clonedSources = JSON.parse(
                        JSON.stringify(values.dataWarehouseSources?.results ?? [])
                    ) as ExternalDataSource[]
                    const sourceIndex = clonedSources.findIndex((n) => n.schemas.find((m) => m.id === schema.id))
                    const schemaIndex = clonedSources[sourceIndex].schemas.findIndex((n) => n.id === schema.id)
                    clonedSources[sourceIndex].schemas[schemaIndex] = schema

                    actions.loadSourcesSuccess({
                        ...values.dataWarehouseSources,
                        results: clonedSources,
                    })

                    await api.externalDataSchemas.update(schema.id, schema)
                    actions.loadSources(null)

                    return null
                },
            },
        ],
    })),
    reducers(() => ({
        sourceReloadingById: [
            {} as Record<string, boolean>,
            {
                reloadSource: (state, { source }) => ({
                    ...state,
                    [source.id]: true,
                }),
                deleteSource: (state, { source }) => ({
                    ...state,
                    [source.id]: true,
                }),
                sourceLoadingFinished: (state, { source }) => ({
                    ...state,
                    [source.id]: false,
                }),
            },
        ],
        schemaReloadingById: [
            {} as Record<string, boolean>,
            {
                schemaLoadingFinished: (state, { schema }) => ({
                    ...state,
                    [schema.id]: false,
                }),
            },
        ],
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    })),
    selectors({
        selfManagedTables: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables): DatabaseSchemaDataWarehouseTable[] => {
                return dataWarehouseTables.filter((table) => !table.source)
            },
        ],
        computedAllSources: [
            (s) => [s.dataWarehouseSources, s.recentActivity, s.selfManagedTables],
            (
                dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
                recentActivity: UnifiedRecentActivity[],
                selfManagedTables: DatabaseSchemaDataWarehouseTable[],
                availableSources: Record<string, any> | null
            ): DashboardDataSource[] => {
                const getSourceType = (
                    sourceType: string,
                    availableSources?: Record<string, any> | null
                ): 'Database' | 'API' => {
                    const fields = availableSources?.[sourceType]?.fields || []
                    const lowerCaseFields = fields.map((f: any) => ({
                        ...f,
                        name: f.name.toLowerCase().replace(/ /g, '_'),
                    }))
                    if (
                        lowerCaseFields.some(
                            (f: any) =>
                                f.name === 'connection_string' ||
                                f.name === 'host' ||
                                f.name === 'port' ||
                                f.name === 'database'
                        )
                    ) {
                        return 'Database'
                    }
                    if (
                        lowerCaseFields.some(
                            (f: any) => f.type === 'oauth' || f.name === 'api_key' || f.name === 'access_token'
                        )
                    ) {
                        return 'API'
                    }
                    return 'API'
                }

                const managed: DashboardDataSource[] = (dataWarehouseSources?.results || []).map(
                    (source: ExternalDataSource): DashboardDataSource => {
                        const sourceActivities = (recentActivity || []).filter(
                            (a) => a.type === 'Data Sync' && a.sourceId === source.id
                        )
                        const totalRows = sourceActivities.reduce(
                            (sum: number, a: UnifiedRecentActivity) => sum + Number(a.rowCount || 0),
                            0
                        )
                        const lastSync = sourceActivities.length > 0 ? sourceActivities[0].created_at : null
                        return {
                            id: source.id,
                            name: source.source_type,
                            type: getSourceType(source.source_type, availableSources),
                            status: source.status,
                            lastSync,
                            rowCount: totalRows,
                            url: `/data-warehouse/sources/managed-${source.id}`,
                        }
                    }
                )

                const selfManaged: DashboardDataSource[] = (selfManagedTables || []).map((table) => ({
                    id: table.id,
                    name: table.name,
                    type: 'Database' as const,
                    status: null,
                    lastSync: null,
                    rowCount: table.row_count ?? null,
                    url: `/data-warehouse/sources/self-managed-${table.id}`,
                }))

                return [...managed, ...selfManaged]
            },
        ],
        filteredSelfManagedTables: [
            (s) => [s.selfManagedTables, s.searchTerm],
            (
                selfManagedTables: DatabaseSchemaDataWarehouseTable[],
                searchTerm: string
            ): DatabaseSchemaDataWarehouseTable[] => {
                if (!searchTerm?.trim()) {
                    return selfManagedTables
                }
                const normalizedSearch = searchTerm.toLowerCase()
                return selfManagedTables.filter((table) => table.name.toLowerCase().includes(normalizedSearch))
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/data-warehouse/*': () => {
            actions.loadSources(null)
        },
    })),
    listeners(({ actions, values, cache }) => ({
        deleteSelfManagedTable: async ({ tableId }) => {
            await api.dataWarehouseTables.delete(tableId)
            actions.loadDatabase()
        },
        refreshSelfManagedTableSchema: async ({ tableId }) => {
            lemonToast.info('Updating schema...')
            await api.dataWarehouseTables.refreshSchema(tableId)
            lemonToast.success('Schema updated')
            actions.loadDatabase()
        },
        deleteSource: async ({ source }) => {
            await api.externalDataSources.delete(source.id)
            actions.loadSources(null)
            actions.sourceLoadingFinished(source)

            posthog.capture('source deleted', { sourceType: source.source_type })
        },
        reloadSource: async ({ source }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSources = JSON.parse(
                JSON.stringify(values.dataWarehouseSources?.results ?? [])
            ) as ExternalDataSource[]
            const sourceIndex = clonedSources.findIndex((n) => n.id === source.id)
            clonedSources[sourceIndex].status = 'Running'
            clonedSources[sourceIndex].schemas = clonedSources[sourceIndex].schemas.map((n) => {
                if (n.should_sync) {
                    return {
                        ...n,
                        status: ExternalDataSchemaStatus.Running,
                    }
                }

                return n
            })

            actions.loadSourcesSuccess({
                ...values.dataWarehouseSources,
                results: clonedSources,
            })

            try {
                await api.externalDataSources.reload(source.id)
                actions.loadSources(null)

                posthog.capture('source reloaded', { sourceType: source.source_type })
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant refresh source at this time')
                }
            }
            actions.sourceLoadingFinished(source)
        },
        updateSchema: (schema) => {
            posthog.capture('schema updated', { shouldSync: schema.should_sync, syncType: schema.sync_type })
        },
        loadSourcesSuccess: () => {
            clearTimeout(cache.refreshTimeout)

            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.refreshTimeout = setTimeout(() => {
                    actions.loadSources(null)
                }, REFRESH_INTERVAL)
            }
        },
        loadSourcesFailure: () => {
            clearTimeout(cache.refreshTimeout)

            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.refreshTimeout = setTimeout(() => {
                    actions.loadSources(null)
                }, REFRESH_INTERVAL)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
    }),
    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
    }),
])
