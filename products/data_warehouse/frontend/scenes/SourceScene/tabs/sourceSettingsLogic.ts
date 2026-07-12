import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { tryShowMCPHint } from 'lib/components/MCPHint/mcpHintLogic'
import { objectsEqual } from 'lib/utils/objects'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SourceConfig, SourceFieldConfig } from '~/queries/schema/schema-general'
import {
    DataWarehouseSyncInterval,
    ExternalDataJob,
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
} from '~/types'

import { groupTablesBySchema } from 'products/data_warehouse/frontend/shared/components/forms/schemaGroupingUtils'
import { SYNC_FREQUENCY_ORDER, clampSyncFrequency } from 'products/data_warehouse/frontend/utils'

import { getUploadedFile } from '../../../shared/components/forms/fileUploads'
import { sourcesDataLogic } from '../../../shared/logics/sourcesDataLogic'
import { availableSourcesLogic } from '../../NewSourceScene/availableSourcesLogic'
import { SSH_FIELD, getErrorsForFields } from '../../NewSourceScene/sourceWizardLogic'
import { sourceSceneLogic } from '../SourceScene'
import type { sourceSettingsLogicType } from './sourceSettingsLogicType'

export interface SourceSettingsLogicProps {
    id: string
    availableSources?: Record<string, SourceConfig>
}

export interface CdcStatus {
    enabled: boolean
    management_mode?: 'posthog' | 'self_managed'
    slot_name?: string
    publication_name?: string
    lag_warning_threshold_mb?: number
    lag_critical_threshold_mb?: number
    slot_exists?: boolean
    publication_exists?: boolean
    lag_bytes?: number | null
    published_tables?: string[]
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

// Read-only/derived fields to keep out of bulk-update payloads. A denylist (not an allowlist of
// writable fields) so new editable fields are sent automatically — a stale allowlist silently
// dropped edits like sync_frequency.
const NON_WRITABLE_SCHEMA_FIELDS = new Set<keyof ExternalDataSourceSchema>([
    'id',
    'name',
    'label',
    'table',
    'last_synced_at',
    'latest_error',
    'status',
    'description',
    'available_columns',
    'incremental',
    'should_sync_default',
])

type SchemaPayloadField = keyof ExternalDataSourceSchema

interface PendingSchemaUpdate {
    revision: number
    schema: ExternalDataSourceSchema
    // Fields changed vs. server state, accumulated across coalesced edits before a flush.
    changedFields: Set<SchemaPayloadField>
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

// PATCH body of only the changed fields (+ id). The backend writes every field it receives, so
// sending an untouched field would clobber it. Nullish → null so a clear is sent (JSON drops undefined).
function buildSchemaUpdatePayload(
    schema: ExternalDataSourceSchema,
    changedFields: Set<SchemaPayloadField>
): Partial<ExternalDataSourceSchema> & Pick<ExternalDataSourceSchema, 'id'> {
    const payload: Partial<ExternalDataSourceSchema> & Pick<ExternalDataSourceSchema, 'id'> = { id: schema.id }
    const assign = payload as Record<string, unknown>

    for (const field of changedFields) {
        assign[field] = schema[field] ?? null
    }

    return payload
}

// Writable fields whose value changed vs. the current schema. No baseline (source not loaded) =>
// treat all as changed so the edit still persists.
function diffSchemaPayloadFields(
    nextSchema: ExternalDataSourceSchema,
    baselineSchema: ExternalDataSourceSchema | undefined
): Set<SchemaPayloadField> {
    const changed = new Set<SchemaPayloadField>()
    const fields = new Set<SchemaPayloadField>([
        ...(Object.keys(nextSchema) as SchemaPayloadField[]),
        ...((baselineSchema ? Object.keys(baselineSchema) : []) as SchemaPayloadField[]),
    ])

    for (const field of fields) {
        if (NON_WRITABLE_SCHEMA_FIELDS.has(field)) {
            continue
        }
        if (!baselineSchema || !objectsEqual(nextSchema[field], baselineSchema[field])) {
            changed.add(field)
        }
    }

    return changed
}

// A failed flush merges its fields into the newer queued edit so the retry re-sends both; the newer
// edit wins on overlap. Otherwise the retry would drop the failed edit's fields.
function foldFailedUpdateIntoPending(failed: PendingSchemaUpdate, pending: PendingSchemaUpdate): PendingSchemaUpdate {
    const mergedSchema = { ...failed.schema }
    const assign = mergedSchema as Record<string, unknown>
    for (const field of pending.changedFields) {
        assign[field] = pending.schema[field]
    }

    return {
        schema: mergedSchema,
        revision: pending.revision,
        changedFields: new Set([...failed.changedFields, ...pending.changedFields]),
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

export const isSensitiveCredentialField = (field: SourceFieldConfig): boolean => {
    return ('secret' in field && !!field.secret) || field.type === 'password'
}

export const removeEmptySensitiveValues = (fields: SourceFieldConfig[], valueObj: Record<string, any>): void => {
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

export const clonePayloadPreservingFiles = (value: unknown): unknown => {
    if (value instanceof File) {
        return value
    }

    if (Array.isArray(value)) {
        return value.map((item) => clonePayloadPreservingFiles(item))
    }

    if (value instanceof Date) {
        return new Date(value.getTime())
    }
    if (value && typeof value === 'object' && value.constructor === Object) {
        return Object.fromEntries(
            Object.entries(value as Record<string, unknown>).map(([key, nestedValue]) => [
                key,
                clonePayloadPreservingFiles(nestedValue),
            ])
        )
    }

    return value
}

// Run a per-schema API action across many schemas; returns how many failed.
export async function runBulkSchemaAction(
    schemas: ExternalDataSourceSchema[],
    action: (schemaId: string) => Promise<unknown>
): Promise<number> {
    const results = await Promise.allSettled(schemas.map((schema) => action(schema.id)))
    return results.filter((result) => result.status === 'rejected').length
}

// Only schemas that are enabled with a configured sync method can be synced on demand.
export function schemasEligibleForSync(schemas: ExternalDataSourceSchema[]): ExternalDataSourceSchema[] {
    return schemas.filter((schema) => !!schema.sync_type && schema.should_sync)
}

export function clampFrequencyForSchema(
    requested: DataWarehouseSyncInterval,
    schema: ExternalDataSourceSchema
): DataWarehouseSyncInterval {
    return clampSyncFrequency(requested, schema.sync_type)
}

function reportBulkResult(verb: string, total: number, failed: number, skipped: number, skipReason = ''): void {
    const succeeded = total - failed
    const parts = [`${verb} ${pluralize(succeeded, 'schema', 'schemas')}`]
    if (failed > 0) {
        parts.push(`${failed} failed`)
    }
    if (skipped > 0) {
        parts.push(`skipped ${skipped}${skipReason ? ` ${skipReason}` : ''}`)
    }
    const message = parts.join(', ')
    if (failed > 0) {
        lemonToast.error(message)
    } else {
        lemonToast.success(message)
    }
}

export const sourceSettingsLogic = kea<sourceSettingsLogicType>([
    path(['products', 'dataWarehouse', 'sourceSettingsLogic']),
    props({} as SourceSettingsLogicProps),
    key(({ id }) => id),
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
        bulkDisable: (schemas: ExternalDataSourceSchema[]) => ({ schemas }),
        bulkSetFrequency: (schemas: ExternalDataSourceSchema[], frequency: DataWarehouseSyncInterval) => ({
            schemas,
            frequency,
        }),
        bulkSyncNow: (schemas: ExternalDataSourceSchema[]) => ({ schemas }),
        bulkResync: (schemas: ExternalDataSourceSchema[]) => ({ schemas }),
        bulkDeleteData: (schemas: ExternalDataSourceSchema[]) => ({ schemas }),
        setCanLoadMoreJobs: (canLoadMoreJobs: boolean) => ({ canLoadMoreJobs }),
        setIsProjectTime: (isProjectTime: boolean) => ({ isProjectTime }),
        setSelectedSchemas: (schemaNames: string[]) => ({ schemaNames }),
        setShowEnabledSchemasOnly: (showEnabledSchemasOnly: boolean) => ({ showEnabledSchemasOnly }),
        setSchemaNameFilter: (schemaNameFilter: string) => ({ schemaNameFilter }),
        setStatusFilter: (status: string | null) => ({ status }),
        setSyncMethodFilter: (syncMethod: string | null) => ({ syncMethod }),
        setFrequencyFilter: (frequency: DataWarehouseSyncInterval | null) => ({ frequency }),
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
        migrateGoogleServiceAccountAuth: true,
        setMigratingGoogleServiceAccountAuth: (migrating: boolean) => ({ migrating }),
        pausePolling: true,
        resumePolling: true,
    }),
    loaders(({ actions, values, cache }) => ({
        source: [
            null as ExternalDataSource | null,
            {
                loadSource: async () => {
                    try {
                        return await api.externalDataSources.get(values.sourceId)
                    } catch (error: any) {
                        // Source soft-deleted. Bounce to the list and swallow
                        // the failure so kea-loaders doesn't toast "Not found".
                        if (error?.status === 404) {
                            router.actions.replace(urls.sources())
                            return null
                        }
                        throw error
                    }
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
        cdcStatus: [
            null as CdcStatus | null,
            {
                // Opens a connection to the customer DB, so it's on-demand (never polled).
                loadCdcStatus: async () => {
                    return await api.externalDataSources.cdc_status(values.sourceId)
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
        // null = no filter applied (show all). For sync method, the sentinel 'none' matches
        // schemas with no sync method set up yet.
        statusFilter: [
            null as string | null,
            {
                setStatusFilter: (_, { status }) => status,
            },
        ],
        syncMethodFilter: [
            null as string | null,
            {
                setSyncMethodFilter: (_, { syncMethod }) => syncMethod,
            },
        ],
        frequencyFilter: [
            null as DataWarehouseSyncInterval | null,
            {
                setFrequencyFilter: (_, { frequency }) => frequency,
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
        pollPauseCount: [
            0 as number,
            {
                pausePolling: (state) => state + 1,
                resumePolling: (state) => Math.max(0, state - 1),
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
        migratingGoogleServiceAccountAuth: [
            false as boolean,
            {
                migrateGoogleServiceAccountAuth: () => true,
                setMigratingGoogleServiceAccountAuth: (_, { migrating }) => migrating,
            },
        ],
        cdcStatusError: [
            null as string | null,
            {
                loadCdcStatus: () => null,
                loadCdcStatusSuccess: () => null,
                loadCdcStatusFailure: (_, { error }) => error || 'Could not read CDC status from your database.',
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
        // Live row counts for in-progress syncs, keyed by schema id. Lets the Schemas tab show
        // progress during the first sync — before the warehouse table (and its row_count) exists,
        // the table column has nothing to render, so we fall back to the running job's rows_synced.
        inProgressRowsBySchema: [
            (s) => [s.jobs],
            (jobs): Record<string, number> => {
                const map: Record<string, number> = {}
                // jobs arrive newest-first; keep the first (latest) running job per schema.
                for (const job of jobs) {
                    if (job.status === ExternalDataJobStatus.Running && !(job.schema.id in map)) {
                        map[job.schema.id] = job.rows_synced
                    }
                }
                return map
            },
        ],
        filteredSchemas: [
            (s) => [
                s.source,
                s.showEnabledSchemasOnly,
                s.schemaNameFilter,
                s.statusFilter,
                s.syncMethodFilter,
                s.frequencyFilter,
            ],
            (
                source,
                showEnabledSchemasOnly,
                schemaNameFilter,
                statusFilter,
                syncMethodFilter,
                frequencyFilter
            ): ExternalDataSourceSchema[] => {
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
                if (statusFilter) {
                    schemas = schemas.filter((schema) => schema.status === statusFilter)
                }
                if (syncMethodFilter) {
                    schemas = schemas.filter((schema) =>
                        syncMethodFilter === 'none' ? !schema.sync_type : schema.sync_type === syncMethodFilter
                    )
                }
                if (frequencyFilter) {
                    schemas = schemas.filter((schema) => schema.sync_frequency === frequencyFilter)
                }
                return schemas
            },
        ],
        // Multi-schema SQL sources have qualified schema names (`namespace.table`); group them by
        // namespace so the Schemas tab matches the wizard's grouping. Single-namespace sources
        // produce one group and render as a flat table.
        groupedFilteredSchemas: [
            (s) => [s.filteredSchemas, s.source],
            (filteredSchemas, source): { schemaName: string; tables: ExternalDataSourceSchema[] }[] =>
                groupTablesBySchema(
                    filteredSchemas,
                    (schema) => schema.name,
                    typeof source?.job_inputs?.schema === 'string' ? source.job_inputs.schema : null
                ),
        ],
        // Distinct values present across the source's schemas, for populating the filter dropdowns.
        schemaFilterOptions: [
            (s) => [s.source],
            (
                source
            ): {
                statuses: string[]
                syncMethods: (Exclude<ExternalDataSourceSchema['sync_type'], null> | 'none')[]
                frequencies: DataWarehouseSyncInterval[]
            } => {
                const schemas = source?.schemas ?? []
                const statuses = new Set<string>()
                const syncMethods = new Set<Exclude<ExternalDataSourceSchema['sync_type'], null> | 'none'>()
                const frequencies = new Set<DataWarehouseSyncInterval>()
                for (const schema of schemas) {
                    if (schema.status) {
                        statuses.add(schema.status)
                    }
                    syncMethods.add(schema.sync_type ?? 'none')
                    if (schema.sync_frequency) {
                        frequencies.add(schema.sync_frequency)
                    }
                }
                return {
                    statuses: Array.from(statuses),
                    syncMethods: Array.from(syncMethods),
                    // Order shortest→longest for a readable dropdown rather than schema-encounter order.
                    frequencies: SYNC_FREQUENCY_ORDER.filter((frequency) => frequencies.has(frequency)),
                }
            },
        ],
    }),
    forms(({ values, actions }) => ({
        sourceConfig: {
            // Real defaults are pushed into the form at runtime by `ConfigurationTab` via
            // `buildKeaFormDefaultFromSourceDetails` + `setJobInputs`/`setSourceConfigValue`.
            // The cast widens the inferred form value type so reads of `access_method`, payload
            // sub-fields, etc. type-check.
            defaults: { prefix: '', description: '', payload: {} } as Record<string, any>,
            errors: (sourceValues) => {
                return getErrorsForFields(values.sourceFieldConfig?.fields ?? [], sourceValues as any, {
                    allowBlankSensitiveFields: true,
                })
            },
            submit: async ({ payload = {}, description, prefix, access_method }) => {
                const sanitizedPayload = clonePayloadPreservingFiles(payload) as Record<string, any>
                if (values.sourceFieldConfig?.fields) {
                    removeEmptySensitiveValues(values.sourceFieldConfig.fields, sanitizedPayload)
                }

                // Handle file uploads
                const sourceFieldConfig = values.sourceFieldConfig
                if (sourceFieldConfig?.fields) {
                    for (const field of sourceFieldConfig.fields) {
                        if (field.type === 'file-upload') {
                            const uploadedFile = getUploadedFile(sanitizedPayload[field.name])
                            if (!uploadedFile) {
                                delete sanitizedPayload[field.name]
                                continue
                            }

                            try {
                                // Assumes we're loading a JSON file
                                const loadedFile: string = await new Promise((resolve, reject) => {
                                    const fileReader = new FileReader()
                                    fileReader.onload = (e) => resolve(e.target?.result as string)
                                    fileReader.onerror = (e) => reject(e)
                                    fileReader.readAsText(uploadedFile)
                                })
                                sanitizedPayload[field.name] = JSON.parse(loadedFile)
                            } catch (e: any) {
                                posthog.captureException(e)
                                lemonToast.error(
                                    `The "${field.name}" file is not valid — it must be a readable JSON file.`
                                )
                                return
                            }
                        }
                    }
                }

                const newJobInputs = {
                    ...values.source?.job_inputs,
                    ...sanitizedPayload,
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
                    tryShowMCPHint('data_warehouse_sources.update', {
                        derivedPrompt: values.source?.source_type
                            ? `Update the configuration on my ${values.source.source_type} source`
                            : undefined,
                    })
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
                            batchSchemaUpdates.map(({ schema, changedFields }) =>
                                buildSchemaUpdatePayload(schema, changedFields)
                            )
                        )

                        for (const pendingUpdate of batchSchemaUpdates) {
                            delete schemaUpdateCache.inFlightSchemaUpdates[pendingUpdate.schema.id]
                        }

                        actions.updateSchemaSuccess(values.source, updatedSchemas[0])

                        const schemasToApply = updatedSchemas.filter((updatedSchema) => {
                            const latestPendingUpdate = schemaUpdateCache.pendingSchemaUpdates[updatedSchema.id]
                            const inFlightUpdate = pendingSchemaUpdates[updatedSchema.id]

                            return (
                                !latestPendingUpdate ||
                                !inFlightUpdate ||
                                latestPendingUpdate.revision <= inFlightUpdate.revision
                            )
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
                        for (const failedUpdate of batchSchemaUpdates) {
                            delete schemaUpdateCache.inFlightSchemaUpdates[failedUpdate.schema.id]

                            // If a newer edit for this schema is queued, fold the failed fields into it
                            // so the retry doesn't silently drop what this request was carrying.
                            const pending = schemaUpdateCache.pendingSchemaUpdates[failedUpdate.schema.id]
                            if (pending) {
                                schemaUpdateCache.pendingSchemaUpdates[failedUpdate.schema.id] =
                                    foldFailedUpdateIntoPending(failedUpdate, pending)
                            }
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

                // Union this edit's changed fields with any not-yet-flushed pending edit's, so
                // coalesced edits send everything that changed — not just the latest field.
                const baselineSchema = values.source?.schemas.find((item) => item.id === schema.id)
                const changedFields = diffSchemaPayloadFields(schema, baselineSchema)
                for (const field of schemaUpdateCache.pendingSchemaUpdates[schema.id]?.changedFields ?? []) {
                    changedFields.add(field)
                }

                schemaUpdateCache.pendingSchemaUpdates[schema.id] = { schema, revision: nextRevision, changedFields }

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

                // Fetch CDC status once per source — here (not a React effect) so team context is set.
                const ji = (values.source?.job_inputs ?? {}) as Record<string, any>
                const cdcEnabled = ji.cdc_enabled === true || ji.cdc_enabled === 'True' || ji.cdc_enabled === 'true'
                if (cdcEnabled && cache.cdcStatusFetchedForSourceId !== values.source?.id) {
                    cache.cdcStatusFetchedForSourceId = values.source?.id
                    actions.loadCdcStatus()
                }

                const breadcrumbName =
                    values.source?.access_method === 'direct'
                        ? values.source?.prefix || values.source?.source_type || 'Source'
                        : values.source?.source_type || 'Source'

                if (values.pollPauseCount === 0) {
                    cache.disposables.add(() => {
                        const timerId = setTimeout(() => {
                            actions.loadSource()
                        }, REFRESH_INTERVAL)
                        return () => clearTimeout(timerId)
                    }, 'sourceRefreshTimeout')
                }

                const sceneLogicInstance =
                    sourceSceneLogic.findMounted({ id: `managed-${props.id}` }) ??
                    sourceSceneLogic.findMounted({ id: props.id })

                sceneLogicInstance?.actions.setBreadcrumbName(breadcrumbName)
            },
            loadSourceFailure: () => {
                if (values.pollPauseCount === 0) {
                    cache.disposables.add(() => {
                        const timerId = setTimeout(() => {
                            actions.loadSource()
                        }, REFRESH_INTERVAL)
                        return () => clearTimeout(timerId)
                    }, 'sourceRefreshTimeout')
                }
            },
            resumePolling: () => {
                // After the reducer runs we may have dropped to 0 — but no fresh load has been
                // scheduled (the prior loadSourceSuccess fired while paused and skipped its
                // reschedule). Kick a load now so the source page resumes auto-refreshing status.
                if (values.pollPauseCount === 0) {
                    actions.loadSource()
                }
            },
            refreshSchemas: async () => {
                try {
                    const {
                        added = 0,
                        deleted = 0,
                        total_tables_seen = 0,
                    } = await api.externalDataSources.refreshSchemas(values.sourceId)
                    actions.loadSource()
                    posthog.capture('schemas refreshed', {
                        sourceType: values.source?.source_type,
                        added,
                        deleted,
                        total_tables_seen,
                    })
                    // Connected and got an empty table list — almost always a permissions
                    // or configuration issue on the source. Warn rather than silently succeed.
                    // If we also just removed previously-tracked schemas, call that out
                    // explicitly so the user knows their tracking list changed.
                    if (total_tables_seen === 0) {
                        const deletedSuffix =
                            deleted > 0
                                ? ` ${deleted} previously tracked table(s) were removed from the tracking list.`
                                : ''
                        lemonToast.warning(
                            `No tables found. Check the source credentials, permissions, and configuration.${deletedSuffix}`
                        )
                        return
                    }
                    if (added === 0 && deleted === 0) {
                        lemonToast.success(`No schema changes — all ${total_tables_seen} table(s) already tracked.`)
                        return
                    }
                    const counts = [added > 0 ? `${added} added` : null, deleted > 0 ? `${deleted} deleted` : null]
                        .filter(Boolean)
                        .join(' / ')
                    lemonToast.success(`Schemas refreshed: ${counts}`)
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
            migrateGoogleServiceAccountAuth: async () => {
                try {
                    const updatedSource = await api.externalDataSources.migrateGoogleServiceAccountToIntegrations(
                        values.sourceId
                    )
                    actions.loadSourceSuccess(updatedSource)
                    lemonToast.success('Migrated to a Google credential')
                } catch (e: any) {
                    lemonToast.error(e.message || "Can't migrate credentials at this time")
                } finally {
                    actions.setMigratingGoogleServiceAccountAuth(false)
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
            bulkDisable: ({ schemas }) => {
                // Reuse the debounced single-schema update — these coalesce into one bulk PATCH.
                schemas.forEach((schema) => actions.updateSchema({ ...schema, should_sync: false }))
                lemonToast.success(`Disabled ${pluralize(schemas.length, 'schema', 'schemas')}`)
            },
            bulkSetFrequency: ({ schemas, frequency }) => {
                // Non-CDC schemas can't sync faster than every 5 minutes — clamp so a bulk edit
                // never pushes them below their allowed floor.
                let clamped = 0
                schemas.forEach((schema) => {
                    const effective = clampFrequencyForSchema(frequency, schema)
                    if (effective !== frequency) {
                        clamped++
                    }
                    actions.updateSchema({ ...schema, sync_frequency: effective })
                })
                const base = `Updated sync frequency for ${pluralize(schemas.length, 'schema', 'schemas')}`
                lemonToast.success(clamped > 0 ? `${base} (${clamped} kept at their 5 min minimum)` : base)
            },
            bulkSyncNow: async ({ schemas }) => {
                // Only schemas that are enabled with a sync method can sync.
                const eligible = schemasEligibleForSync(schemas)
                const skipped = schemas.length - eligible.length
                if (eligible.length === 0) {
                    lemonToast.warning('None of the selected schemas are enabled with a sync method')
                    return
                }
                const failed = await runBulkSchemaAction(eligible, (id) => api.externalDataSchemas.reload(id))
                actions.loadSource()
                actions.loadJobs()
                posthog.capture('schemas bulk synced', {
                    sourceType: values.source?.source_type,
                    count: eligible.length,
                })
                reportBulkResult(
                    'Started sync for',
                    eligible.length,
                    failed,
                    skipped,
                    'disabled or missing sync method'
                )
            },
            bulkResync: async ({ schemas }) => {
                const failed = await runBulkSchemaAction(schemas, (id) => api.externalDataSchemas.resync(id))
                actions.loadSource()
                actions.loadJobs()
                posthog.capture('schemas bulk resynced', {
                    sourceType: values.source?.source_type,
                    count: schemas.length,
                })
                reportBulkResult('Resyncing', schemas.length, failed, 0)
            },
            bulkDeleteData: async ({ schemas }) => {
                const failed = await runBulkSchemaAction(schemas, (id) => api.externalDataSchemas.delete_data(id))
                actions.loadSource()
                posthog.capture('schemas bulk data deleted', {
                    sourceType: values.source?.source_type,
                    count: schemas.length,
                })
                reportBulkResult('Deleted data for', schemas.length, failed, 0)
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
