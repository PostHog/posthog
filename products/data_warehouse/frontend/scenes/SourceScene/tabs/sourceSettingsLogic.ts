import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual } from 'lib/utils'
import { sceneLogic } from 'scenes/sceneLogic'

import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'
import {
    ExternalDataJob,
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
} from '~/types'

import { sourcesDataLogic } from '../../../shared/logics/sourcesDataLogic'
import { availableSourcesLogic } from '../../NewSourceScene/availableSourcesLogic'
import {
    SSH_FIELD,
    buildKeaFormDefaultFromSourceDetails,
    getErrorsForFields,
} from '../../NewSourceScene/sourceWizardLogic'
import { sourceSceneLogic } from '../SourceScene'
import type { sourceSettingsLogicType } from './sourceSettingsLogicType'

export interface SourceSettingsLogicProps {
    id: string
    tabId?: string
    availableSources?: Record<string, SourceConfig>
}

const REFRESH_INTERVAL = 5000
const SCHEMA_UPDATE_DEBOUNCE_MS = 500
const JOBS_POLL_MAX_BACKOFF_MS = 60000
const JOBS_POLL_TRANSIENT_STATUSES = new Set([408, 502, 503, 504])

function isTransientGatewayError(error: unknown): boolean {
    const status = (error as { status?: number } | null | undefined)?.status
    return typeof status === 'number' && JOBS_POLL_TRANSIENT_STATUSES.has(status)
}

function nextJobsPollDelay(softFailureCount: number): number {
    if (softFailureCount <= 0) {
        return REFRESH_INTERVAL
    }
    const exponential = Math.min(REFRESH_INTERVAL * 2 ** softFailureCount, JOBS_POLL_MAX_BACKOFF_MS)
    // Equal-jitter: spread retries over [0.5x, 1.0x] to avoid synchronized polling after a gateway blip
    return exponential * (0.5 + Math.random() * 0.5)
}

interface PendingSchemaUpdate {
    revision: number
    schema: ExternalDataSourceSchema
}

interface SchemaUpdateCache {
    pendingSchemaUpdates?: Record<string, PendingSchemaUpdate>
    inFlightSchemaUpdates?: Record<string, PendingSchemaUpdate>
    schemaUpdateRevisions?: Record<string, number>
    schemaUpdateFlushTimer?: ReturnType<typeof setTimeout> | null
    reapplyingOptimisticSource?: boolean
}

function applySchemaToSource(
    source: ExternalDataSource | null,
    schema: ExternalDataSourceSchema
): ExternalDataSource | null {
    if (!source) {
        return source
    }

    const clonedSource = JSON.parse(JSON.stringify(source)) as ExternalDataSource
    const schemaIndex = clonedSource.schemas.findIndex((item) => item.id === schema.id)

    if (schemaIndex === -1) {
        return source
    }

    clonedSource.schemas[schemaIndex] = schema
    return clonedSource
}

function applyPendingSchemaUpdatesToSource(
    source: ExternalDataSource | null,
    pendingSchemaUpdates: Record<string, PendingSchemaUpdate>
): ExternalDataSource | null {
    if (!source) {
        return source
    }

    return Object.values(pendingSchemaUpdates).reduce<ExternalDataSource | null>(
        (currentSource, pendingUpdate) => applySchemaToSource(currentSource, pendingUpdate.schema),
        source
    )
}

function applySchemasToSource(
    source: ExternalDataSource | null,
    schemas: ExternalDataSourceSchema[]
): ExternalDataSource | null {
    return schemas.reduce<ExternalDataSource | null>(
        (currentSource, schema) => applySchemaToSource(currentSource, schema),
        source
    )
}

function buildSchemaUpdatePayload(
    schema: ExternalDataSourceSchema
): Pick<
    ExternalDataSourceSchema,
    | 'id'
    | 'should_sync'
    | 'sync_type'
    | 'incremental_field'
    | 'incremental_field_type'
    | 'sync_frequency'
    | 'sync_time_of_day'
    | 'cdc_table_mode'
> {
    return {
        id: schema.id,
        should_sync: schema.should_sync,
        sync_type: schema.sync_type,
        incremental_field: schema.incremental_field,
        incremental_field_type: schema.incremental_field_type,
        sync_frequency: schema.sync_frequency,
        sync_time_of_day: schema.sync_time_of_day,
        cdc_table_mode: schema.cdc_table_mode,
    }
}

function getSchemaUpdateCache(cache: SchemaUpdateCache): Required<SchemaUpdateCache> {
    cache.pendingSchemaUpdates ??= {}
    cache.inFlightSchemaUpdates ??= {}
    cache.schemaUpdateRevisions ??= {}
    cache.schemaUpdateFlushTimer ??= null
    cache.reapplyingOptimisticSource ??= false

    return cache as Required<SchemaUpdateCache>
}

function getOptimisticSchemaUpdates(cache: Required<SchemaUpdateCache>): Record<string, PendingSchemaUpdate> {
    return {
        ...cache.inFlightSchemaUpdates,
        ...cache.pendingSchemaUpdates,
    }
}

function hasOptimisticSchemaChanges(
    source: ExternalDataSource | null,
    optimisticSchemaUpdates: Record<string, PendingSchemaUpdate>
): boolean {
    if (!source) {
        return false
    }

    return Object.values(optimisticSchemaUpdates).some(({ schema }) => {
        const currentSchema = source.schemas.find((item) => item.id === schema.id)
        return !!currentSchema && !objectsEqual(currentSchema, schema)
    })
}

const isSensitiveCredentialField = (field: SourceFieldConfig): boolean => {
    return field.type === 'password' || field.name === 'private_key'
}

const removeEmptySensitiveValues = (fields: SourceFieldConfig[], valueObj: Record<string, any>): void => {
    for (const field of fields) {
        if (field.type === 'switch-group') {
            const groupValue = valueObj[field.name]
            if (groupValue && typeof groupValue === 'object') {
                removeEmptySensitiveValues(field.fields, groupValue)
            }
            continue
        }

        if (field.type === 'select') {
            const hasOptionFields = !!field.options.filter((option) => (option.fields?.length ?? 0) > 0).length
            if (!hasOptionFields) {
                continue
            }
            const selectValue = valueObj[field.name]
            if (selectValue && typeof selectValue === 'object') {
                const selection = selectValue.selection
                const selectedOptionFields = field.options.find((option) => option.value === selection)?.fields ?? []
                removeEmptySensitiveValues(selectedOptionFields, selectValue)
            }
            continue
        }

        if (field.type === 'ssh-tunnel') {
            const tunnelValue = valueObj[field.name]
            if (tunnelValue && typeof tunnelValue === 'object') {
                removeEmptySensitiveValues(SSH_FIELD.fields, tunnelValue)
            }
            continue
        }

        if (isSensitiveCredentialField(field) && valueObj[field.name] === '') {
            delete valueObj[field.name]
        }
    }
}

export const sourceSettingsLogic = kea<sourceSettingsLogicType>([
    path(['products', 'dataWarehouse', 'sourceSettingsLogic']),
    props({} as SourceSettingsLogicProps),
    key(({ id, tabId }) => (tabId ? `${id}-${tabId}` : id)),
    connect(() => ({
        values: [availableSourcesLogic, ['availableSources']],
        actions: [sourcesDataLogic, ['updateSource']],
    })),
    actions({
        setSourceId: (id: string) => ({ id }),
        reloadSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        resyncSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        cancelSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        deleteTable: (schema: ExternalDataSourceSchema) => ({ schema }),
        setCanLoadMoreJobs: (canLoadMoreJobs: boolean) => ({ canLoadMoreJobs }),
        setIsProjectTime: (isProjectTime: boolean) => ({ isProjectTime }),
        setSelectedSchemas: (schemaNames: string[]) => ({ schemaNames }),
        setShowEnabledSchemasOnly: (showEnabledSchemasOnly: boolean) => ({ showEnabledSchemasOnly }),
        setSchemaNameFilter: (schemaNameFilter: string) => ({ schemaNameFilter }),
        syncNow: true,
        setSyncingNow: (syncing: boolean) => ({ syncing }),
        refreshSchemas: true,
        setRefreshingSchemas: (refreshing: boolean) => ({ refreshing }),
        updateSchema: (schema: ExternalDataSourceSchema) => schema,
        updateSchemaSuccess: (source: ExternalDataSource | null, payload?: ExternalDataSourceSchema) => ({
            source,
            payload,
        }),
        updateSchemaFailure: (error: string, errorObject?: any) => ({ error, errorObject }),
    }),
    loaders(({ actions, values, cache }) => ({
        source: [
            null as ExternalDataSource | null,
            {
                loadSource: async () => {
                    return await api.externalDataSources.get(values.sourceId)
                },
            },
        ],
        jobs: [
            [] as ExternalDataJob[],
            {
                loadJobs: async () => {
                    const schemas = values.selectedSchemas.length > 0 ? values.selectedSchemas : undefined

                    try {
                        let result: ExternalDataJob[]
                        if (values.jobs.length === 0) {
                            result = await api.externalDataSources.jobs(values.sourceId, null, null, schemas)
                        } else {
                            // Re-fetch recent jobs without an `after` filter to get updated statuses.
                            // The API returns up to 50 jobs sorted by created_at desc, so this
                            // will refresh the status of recent jobs (e.g. Running -> Completed).
                            const freshJobs = await api.externalDataSources.jobs(values.sourceId, null, null, schemas)

                            // Merge fresh jobs with existing jobs, preferring the fresh data
                            const jobsById = new Map(values.jobs.map((job) => [job.id, job]))
                            for (const job of freshJobs) {
                                jobsById.set(job.id, job)
                            }

                            // Sort by created_at descending (newest first)
                            result = Array.from(jobsById.values()).sort(
                                (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                            )
                        }
                        cache.jobsPollSoftFailureCount = 0
                        return result
                    } catch (error) {
                        // Gateway timeouts / transient upstream errors are expected when the jobs
                        // query is slow. Swallow them here so the 5s poll doesn't become a source
                        // of error-tracking noise; loadJobsSuccess reschedules with backoff.
                        if (isTransientGatewayError(error)) {
                            cache.jobsPollSoftFailureCount = (cache.jobsPollSoftFailureCount ?? 0) + 1
                            return values.jobs
                        }
                        throw error
                    }
                },
                loadMoreJobs: async () => {
                    const schemas = values.selectedSchemas.length > 0 ? values.selectedSchemas : undefined
                    const hasJobs = values.jobs.length > 0
                    if (hasJobs) {
                        const lastJobCreatedAt = values.jobs[values.jobs.length - 1].created_at
                        const oldJobs = await api.externalDataSources.jobs(
                            values.sourceId,
                            lastJobCreatedAt,
                            null,
                            schemas
                        )

                        if (oldJobs.length === 0) {
                            actions.setCanLoadMoreJobs(false)
                            return values.jobs
                        }

                        return [...values.jobs, ...oldJobs]
                    }

                    return values.jobs
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        sourceId: [
            props.id,
            {
                setSourceId: (_, { id }) => id,
            },
        ],
        canLoadMoreJobs: [
            true as boolean,
            {
                setCanLoadMoreJobs: (_, { canLoadMoreJobs }) => canLoadMoreJobs,
                setSourceId: () => true,
            },
        ],
        isProjectTime: [
            false as boolean,
            {
                setIsProjectTime: (_, { isProjectTime }) => isProjectTime,
            },
        ],
        selectedSchemas: [
            [] as string[],
            {
                setSelectedSchemas: (_, { schemaNames }) => schemaNames,
            },
        ],
        showEnabledSchemasOnly: [
            false as boolean,
            { persist: true },
            {
                setShowEnabledSchemasOnly: (_, { showEnabledSchemasOnly }) => showEnabledSchemasOnly,
            },
        ],
        schemaNameFilter: [
            '' as string,
            {
                setSchemaNameFilter: (_, { schemaNameFilter }) => schemaNameFilter,
            },
        ],
        syncingNow: [
            false as boolean,
            {
                setSyncingNow: (_, { syncing }) => syncing,
                syncNow: () => true,
            },
        ],
        refreshingSchemas: [
            false as boolean,
            {
                setRefreshingSchemas: (_, { refreshing }) => refreshing,
                refreshSchemas: () => true,
            },
        ],
        sourceConfigLoading: [
            false as boolean,
            {
                submitSourceConfigRequest: () => true,
                submitSourceConfigSuccess: () => false,
                submitSourceConfigFailure: () => false,
            },
        ],
    })),
    selectors({
        sourceFieldConfig: [
            (s) => [s.source, s.availableSources],
            (source, availableSources) => {
                if (!source || !availableSources) {
                    return null
                }

                return availableSources[source.source_type]
            },
        ],
        filteredSchemas: [
            (s) => [s.source, s.showEnabledSchemasOnly, s.schemaNameFilter],
            (source, showEnabledSchemasOnly, schemaNameFilter): ExternalDataSourceSchema[] => {
                if (!source?.schemas) {
                    return []
                }
                let schemas = source.schemas
                if (showEnabledSchemasOnly) {
                    schemas = schemas.filter((schema) => schema.should_sync)
                }
                if (schemaNameFilter) {
                    const filter = schemaNameFilter.toLowerCase()
                    schemas = schemas.filter((schema) => (schema.label ?? schema.name).toLowerCase().includes(filter))
                }
                return schemas
            },
        ],
    }),
    forms(({ values, actions, props }) => ({
        sourceConfig: {
            defaults: buildKeaFormDefaultFromSourceDetails(props.availableSources ?? {}),
            errors: (sourceValues) => {
                return getErrorsForFields(values.sourceFieldConfig?.fields ?? [], sourceValues as any, {
                    allowBlankSensitiveFields: true,
                })
            },
            submit: async ({ payload = {}, description, prefix, access_method }) => {
                const sanitizedPayload = JSON.parse(JSON.stringify(payload)) as Record<string, any>
                if (values.sourceFieldConfig?.fields) {
                    removeEmptySensitiveValues(values.sourceFieldConfig.fields, sanitizedPayload)
                }

                const newJobInputs = {
                    ...values.source?.job_inputs,
                    ...sanitizedPayload,
                }

                // Handle file uploads
                const sourceFieldConfig = values.sourceFieldConfig
                if (sourceFieldConfig?.fields) {
                    for (const field of sourceFieldConfig.fields) {
                        if (field.type === 'file-upload' && sanitizedPayload[field.name]) {
                            try {
                                // Assumes we're loading a JSON file
                                const loadedFile: string = await new Promise((resolve, reject) => {
                                    const fileReader = new FileReader()
                                    fileReader.onload = (e) => resolve(e.target?.result as string)
                                    fileReader.onerror = (e) => reject(e)
                                    fileReader.readAsText(sanitizedPayload[field.name][0])
                                })
                                newJobInputs[field.name] = JSON.parse(loadedFile)
                            } catch {
                                lemonToast.error('File is not valid')
                                return
                            }
                        }
                    }
                }

                try {
                    await sourcesDataLogic.asyncActions.updateSource({
                        ...values.source!,
                        job_inputs: newJobInputs,
                        prefix: prefix !== undefined ? prefix : values.source?.prefix,
                        access_method: access_method !== undefined ? access_method : values.source?.access_method,
                        description: description !== '' ? description : (values.source?.description ?? null),
                    })
                    actions.loadSource()
                    lemonToast.success('Source updated')
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error('Cant update source at this time')
                    }
                }
            },
        },
    })),
    listeners(({ values, actions, props, cache }) => {
        const schemaUpdateCache = getSchemaUpdateCache(cache)

        const scheduleSchemaUpdateFlush = (): void => {
            if (schemaUpdateCache.schemaUpdateFlushTimer) {
                clearTimeout(schemaUpdateCache.schemaUpdateFlushTimer)
            }

            schemaUpdateCache.schemaUpdateFlushTimer = setTimeout(() => {
                schemaUpdateCache.schemaUpdateFlushTimer = null

                const pendingSchemaUpdates = { ...schemaUpdateCache.pendingSchemaUpdates }
                if (Object.keys(pendingSchemaUpdates).length === 0) {
                    return
                }

                if (Object.keys(schemaUpdateCache.inFlightSchemaUpdates).length > 0) {
                    return
                }

                schemaUpdateCache.pendingSchemaUpdates = {}
                schemaUpdateCache.inFlightSchemaUpdates = pendingSchemaUpdates

                void (async () => {
                    const batchSchemaUpdates = Object.values(pendingSchemaUpdates)

                    try {
                        const updatedSchemas = await api.externalDataSources.bulkUpdateSchemas(
                            values.sourceId,
                            batchSchemaUpdates.map(({ schema }) => buildSchemaUpdatePayload(schema))
                        )

                        for (const pendingUpdate of batchSchemaUpdates) {
                            delete schemaUpdateCache.inFlightSchemaUpdates[pendingUpdate.schema.id]
                        }

                        actions.updateSchemaSuccess(values.source, updatedSchemas[0])

                        const schemasToApply = updatedSchemas.filter((updatedSchema) => {
                            const latestPendingUpdate = schemaUpdateCache.pendingSchemaUpdates[updatedSchema.id]
                            const inFlightUpdate = pendingSchemaUpdates[updatedSchema.id]

                            return !latestPendingUpdate || latestPendingUpdate.revision <= inFlightUpdate.revision
                        })

                        if (schemasToApply.length > 0) {
                            const nextSource = applySchemasToSource(values.source, schemasToApply)
                            if (nextSource) {
                                actions.loadSourceSuccess(nextSource)
                            }
                        }

                        if (Object.keys(schemaUpdateCache.pendingSchemaUpdates).length > 0) {
                            scheduleSchemaUpdateFlush()
                        }
                    } catch (error: any) {
                        for (const pendingUpdate of batchSchemaUpdates) {
                            delete schemaUpdateCache.inFlightSchemaUpdates[pendingUpdate.schema.id]
                        }

                        if (Object.keys(schemaUpdateCache.pendingSchemaUpdates).length > 0) {
                            scheduleSchemaUpdateFlush()
                        } else {
                            actions.loadSource()
                        }

                        actions.updateSchemaFailure(error?.message || "Can't update schemas at this time", error)
                        lemonToast.error(error?.message || "Can't update schemas at this time")
                    }
                })()
            }, SCHEMA_UPDATE_DEBOUNCE_MS)
        }

        return {
            updateSchema: (schema) => {
                const nextRevision = (schemaUpdateCache.schemaUpdateRevisions[schema.id] ?? 0) + 1

                schemaUpdateCache.schemaUpdateRevisions[schema.id] = nextRevision
                schemaUpdateCache.pendingSchemaUpdates[schema.id] = { schema, revision: nextRevision }

                const optimisticSource = applyPendingSchemaUpdatesToSource(
                    values.source,
                    getOptimisticSchemaUpdates(schemaUpdateCache)
                )
                if (optimisticSource) {
                    schemaUpdateCache.reapplyingOptimisticSource = true
                    actions.loadSourceSuccess(optimisticSource)
                }

                scheduleSchemaUpdateFlush()
            },
            loadSourceSuccess: () => {
                const optimisticSchemaUpdates = getOptimisticSchemaUpdates(schemaUpdateCache)

                if (schemaUpdateCache.reapplyingOptimisticSource) {
                    schemaUpdateCache.reapplyingOptimisticSource = false
                } else if (hasOptimisticSchemaChanges(values.source, optimisticSchemaUpdates)) {
                    const optimisticSource = applyPendingSchemaUpdatesToSource(values.source, optimisticSchemaUpdates)
                    if (optimisticSource) {
                        schemaUpdateCache.reapplyingOptimisticSource = true
                        actions.loadSourceSuccess(optimisticSource)
                        return
                    }
                }

                const isDirectQueryEnabled =
                    !!featureFlagLogic.values.featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]
                const breadcrumbName =
                    isDirectQueryEnabled && values.source?.access_method === 'direct'
                        ? values.source?.prefix || values.source?.source_type || 'Source'
                        : values.source?.source_type || 'Source'

                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadSource()
                    }, REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'sourceRefreshTimeout')

                const tabId = props.tabId ?? sceneLogic.findMounted()?.values.activeTabId ?? undefined
                const sceneLogicInstance =
                    sourceSceneLogic.findMounted({ id: `managed-${props.id}`, tabId }) ??
                    sourceSceneLogic.findMounted({ id: props.id, tabId })

                sceneLogicInstance?.actions.setBreadcrumbName(breadcrumbName)
            },
            loadSourceFailure: () => {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadSource()
                    }, REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'sourceRefreshTimeout')
            },
            refreshSchemas: async () => {
                try {
                    const { added = 0, deleted = 0 } = await api.externalDataSources.refreshSchemas(values.sourceId)
                    actions.loadSource()
                    posthog.capture('schemas refreshed', {
                        sourceType: values.source?.source_type,
                        added,
                        deleted,
                    })
                    const parts = ['Schemas refreshed']
                    if (added > 0 || deleted > 0) {
                        parts.push(
                            [added > 0 ? `${added} added` : null, deleted > 0 ? `${deleted} deleted` : null]
                                .filter(Boolean)
                                .join(' / ')
                        )
                    }
                    lemonToast.success(parts.join(', '))
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error("Can't refresh schemas at this time")
                    }
                } finally {
                    actions.setRefreshingSchemas(false)
                }
            },
            setSelectedSchemas: () => {
                // Reset jobs so loadJobs fetches fresh data for the new filter
                // instead of merging with stale results from a different selection
                actions.loadJobsSuccess([])
                actions.setCanLoadMoreJobs(true)
                actions.loadJobs()
            },
            loadJobsSuccess: () => {
                const delay = nextJobsPollDelay(cache.jobsPollSoftFailureCount ?? 0)
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadJobs()
                    }, delay)
                    return () => clearTimeout(timerId)
                }, 'jobsRefreshTimeout')
            },
            loadJobsFailure: () => {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadJobs()
                    }, REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'jobsRefreshTimeout')
            },
            syncNow: async () => {
                try {
                    await api.externalDataSources.reload(values.sourceId)
                    actions.loadSource()
                    actions.loadJobs()
                    lemonToast.success('Sync started')
                    posthog.capture('sync now triggered', { sourceType: values.source?.source_type })
                } catch (e: any) {
                    lemonToast.error(e.message || "Can't start sync at this time")
                } finally {
                    actions.setSyncingNow(false)
                }
            },
            reloadSchema: async ({ schema }) => {
                // Optimistic UI updates before sending updates to the backend
                const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
                const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
                clonedSource.status = ExternalDataJobStatus.Running
                clonedSource.schemas[schemaIndex].status = ExternalDataSchemaStatus.Running

                actions.loadSourceSuccess(clonedSource)

                try {
                    await api.externalDataSchemas.reload(schema.id)

                    posthog.capture('schema reloaded', { sourceType: clonedSource.source_type })
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error('Cant reload schema at this time')
                    }
                }
            },
            resyncSchema: async ({ schema }) => {
                // Optimistic UI updates before sending updates to the backend
                const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
                const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
                clonedSource.status = ExternalDataJobStatus.Running
                clonedSource.schemas[schemaIndex].status = ExternalDataSchemaStatus.Running

                actions.loadSourceSuccess(clonedSource)

                try {
                    await api.externalDataSchemas.resync(schema.id)

                    posthog.capture('schema resynced', { sourceType: clonedSource.source_type })
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error('Cant refresh schema at this time')
                    }
                }
            },
            cancelSchema: async ({ schema }) => {
                try {
                    await api.externalDataSchemas.cancel(schema.id)

                    actions.loadSource()
                    posthog.capture('schema sync cancelled', { sourceType: values.source?.source_type })
                    lemonToast.success('Sync cancelled')
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error("Can't cancel sync at this time")
                    }
                }
            },
            deleteTable: async ({ schema }) => {
                // Optimistic UI updates before sending updates to the backend
                const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
                const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
                if (schemaIndex === -1) {
                    lemonToast.error('Schema not found')
                    return
                }
                clonedSource.schemas[schemaIndex].table = undefined
                clonedSource.schemas[schemaIndex].status = undefined
                clonedSource.schemas[schemaIndex].last_synced_at = undefined
                actions.loadSourceSuccess(clonedSource)

                try {
                    await api.externalDataSchemas.delete_data(schema.id)

                    posthog.capture('schema data deleted', { sourceType: clonedSource.source_type })
                    lemonToast.success(`Data for ${schema.label ?? schema.name} has been deleted`)
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error("Can't delete data at this time")
                    }
                }
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.loadSource()
    }),

    beforeUnmount(({ cache }) => {
        const schemaUpdateCache = getSchemaUpdateCache(cache)

        if (schemaUpdateCache.schemaUpdateFlushTimer) {
            clearTimeout(schemaUpdateCache.schemaUpdateFlushTimer)
        }
    }),
])
