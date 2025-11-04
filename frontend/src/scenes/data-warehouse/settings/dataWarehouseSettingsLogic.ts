import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'
import { DataWarehouseViewLink, ExternalDataSchemaStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { dataWarehouseJoinsLogic } from '../external/dataWarehouseJoinsLogic'
import type { dataWarehouseSettingsLogicType } from './dataWarehouseSettingsLogicType'

const REFRESH_INTERVAL = 10000

export const dataWarehouseSettingsLogic = kea<dataWarehouseSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSettingsLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables'],
            externalDataSourcesLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading'],
        ],
        actions: [
            databaseTableListLogic,
            ['loadDatabase'],
            dataWarehouseJoinsLogic,
            ['loadJoins'],
            externalDataSourcesLogic,
            ['loadSources', 'loadSourcesSuccess', 'updateSource', 'updateSourceRevenueAnalyticsConfig'],
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
        deleteJoin: (join: DataWarehouseViewLink) => ({ join }),
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
        hasZendeskSource: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources): boolean => {
                const sources = dataWarehouseSources?.results
                if (!sources) {
                    return false
                }

                return !!sources.some((source) => source?.source_type === 'Zendesk')
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
            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadSources(null)
                    }, REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
        loadSourcesFailure: () => {
            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadSources(null)
                    }, REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
        deleteJoin: ({ join }): void => {
            void deleteWithUndo({
                endpoint: api.dataWarehouseViewLinks.determineDeleteEndpoint(),
                object: {
                    id: join.id,
                    name: `${join.field_name} on ${join.source_table_name}`,
                },
                callback: () => {
                    actions.loadDatabase()
                    actions.loadJoins()
                },
            }).catch((e) => {
                lemonToast.error(`Failed to delete warehouse view link: ${e.detail}`)
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
    }),
    beforeUnmount(() => {
        // Disposables plugin handles cleanup automatically
    }),
])
