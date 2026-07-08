import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonSelectOption,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Link,
    Tooltip,
    lemonToast,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DataWarehouseSyncInterval, ExternalDataSource, ExternalDataSourceSchema, RowFilter } from '~/types'

import {
    SyncMethodForm,
    SyncMethodFormHandle,
} from 'products/data_warehouse/frontend/shared/components/forms/SyncMethodForm'
import {
    SourceEditorAction,
    useSourceEditorAccess,
} from 'products/data_warehouse/frontend/shared/components/SourceEditorAction'
import {
    StatusTagSetting,
    SyncFrequencyLabelMap,
    SyncTypeLabelMap,
    allowedSyncFrequencies,
    defaultQuery,
    syncAnchorIntervalToHumanReadable,
} from 'products/data_warehouse/frontend/utils'

import { ColumnSelectionPicker } from '../SourceScene/tabs/ColumnSelectionModal'
import { RowFilterEditor } from '../SourceScene/tabs/RowFilterEditor'
import { validateRowFilters } from '../SourceScene/tabs/rowFilterUtils'
import { columnAnnotationsLogic } from './columnAnnotationsLogic'
import { SchemaConfigurationSection, schemaSceneLogic } from './schemaSceneLogic'

// null means "all columns" on either side, so switching to null after a partial list flags
// every previously-excluded column as added.
function getAddedColumns(prev: string[] | null, next: string[] | null, available: { name: string }[]): string[] {
    const allColumns = available.map((c) => c.name)
    const prevSet = new Set(prev ?? allColumns)
    const nextSet = new Set(next ?? allColumns)
    return allColumns.filter((c) => nextSet.has(c) && !prevSet.has(c))
}

// null normalizes to "all columns" so an explicit full list and null compare equal.
function sameColumns(a: string[] | null, b: string[] | null, available: { name: string }[]): boolean {
    const allColumns = available.map((c) => c.name)
    const setA = new Set(a ?? allColumns)
    const setB = new Set(b ?? allColumns)
    return setA.size === setB.size && [...setA].every((c) => setB.has(c))
}

export interface ConfigurationTabProps {
    sourceId: string
    schema: ExternalDataSourceSchema
    source: ExternalDataSource | null
    section: SchemaConfigurationSection
    onConfigureSyncMethod: () => void
    onViewSyncHistory: () => void
}

export function ConfigurationTab({
    sourceId,
    schema,
    source,
    section,
    onConfigureSyncMethod,
    onViewSyncHistory,
}: ConfigurationTabProps): JSX.Element {
    const logic = schemaSceneLogic({ sourceId, schemaId: schema.id })
    const { isProjectTime, refreshingSchemas, resyncingSchema, supportsRowFilters } = useValues(logic)
    const { setIsProjectTime, updateSchema, reloadSchema, resyncSchema, cancelSchema, deleteTable, refreshSchemas } =
        useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    switch (section) {
        case 'details':
            return (
                <DetailsSection
                    source={source}
                    schema={schema}
                    reloadSchema={reloadSchema}
                    cancelSchema={cancelSchema}
                    updateSchema={updateSchema}
                    onConfigureSyncMethod={onConfigureSyncMethod}
                    onViewSyncHistory={onViewSyncHistory}
                />
            )
        case 'sync-method':
            return <SyncMethodSection sourceId={sourceId} source={source} schema={schema} />
        case 'columns':
            return (
                <ColumnsAndRowFiltersSection
                    source={source}
                    schema={schema}
                    updateSchema={updateSchema}
                    resyncSchema={resyncSchema}
                    refreshSchemas={refreshSchemas}
                    refreshingSchemas={refreshingSchemas}
                    supportsRowFilters={supportsRowFilters}
                />
            )
        case 'schedule':
            return (
                <ScheduleSection
                    sourceId={sourceId}
                    source={source}
                    schema={schema}
                    isProjectTime={isProjectTime}
                    setIsProjectTime={setIsProjectTime}
                />
            )
        case 'descriptions':
            // Deep-link guard: the section nav already hides this when the flag is off.
            return featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SEMANTIC_ENRICHMENT] ? (
                <DescriptionsSection schema={schema} />
            ) : (
                <></>
            )
        case 'danger-zone':
            return (
                <DangerZoneSection
                    source={source}
                    schema={schema}
                    resyncSchema={resyncSchema}
                    resyncingSchema={resyncingSchema}
                    deleteTable={deleteTable}
                />
            )
    }
}

function SectionHeader({ title, description }: { title: string; description?: string }): JSX.Element {
    return (
        <div className="mb-4">
            <h2 className="text-base font-semibold mb-1">{title}</h2>
            {description && <p className="text-sm text-secondary">{description}</p>}
        </div>
    )
}

function DetailsSection({
    source,
    schema,
    reloadSchema,
    cancelSchema,
    updateSchema,
    onConfigureSyncMethod,
    onViewSyncHistory,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    reloadSchema: (schema: ExternalDataSourceSchema) => void
    cancelSchema: (schema: ExternalDataSourceSchema) => void
    updateSchema: (schema: ExternalDataSourceSchema) => void
    onConfigureSyncMethod: () => void
    onViewSyncHistory: () => void
}): JSX.Element {
    return (
        <div>
            <SectionHeader
                title="Details"
                description="Enable or disable syncing for this schema, see its current state, and trigger a sync on demand."
            />
            <div className="border rounded p-4 bg-surface-primary flex flex-col gap-3">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex flex-col">
                        <span>Enabled</span>
                        <span className="text-xs text-muted max-w-md">
                            When enabled, this schema runs on the configured schedule and data is imported into PostHog.
                            Disabling pauses all syncs — existing data stays in place but is not updated until you
                            re-enable.
                        </span>
                    </div>
                    <SourceEditorAction source={source}>
                        <LemonSwitch
                            checked={schema.should_sync}
                            label={schema.should_sync ? 'Syncing' : 'Disabled'}
                            onChange={(active) => {
                                if (active && !schema.sync_type) {
                                    // No sync method saved yet — open the sync method section to set one up.
                                    onConfigureSyncMethod()
                                    return
                                }
                                if (!active && schema.sync_type === 'cdc') {
                                    LemonDialog.open({
                                        title: 'Disable CDC table?',
                                        content: (
                                            <div className="text-sm text-secondary space-y-2">
                                                <p>
                                                    Disabling <strong>{schema.table?.name ?? schema.name}</strong> will
                                                    remove it from the replication publication. Changes made while
                                                    disabled will be permanently lost.
                                                </p>
                                                <p>
                                                    Re-enabling this table will require a <strong>full resync</strong>{' '}
                                                    to ensure data consistency.
                                                </p>
                                            </div>
                                        ),
                                        primaryButton: {
                                            children: 'Disable',
                                            status: 'danger',
                                            onClick: () => updateSchema({ ...schema, should_sync: false }),
                                        },
                                        secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                    })
                                } else if (!active && schema.sync_type === 'webhook') {
                                    LemonDialog.open({
                                        title: 'Disable webhook sync?',
                                        description:
                                            'Turning off this table will stop the webhook from consuming any more data. When you re-enable it, a full refresh sync will need to be completed to ensure no data is missing.',
                                        primaryButton: {
                                            children: 'Disable',
                                            status: 'danger',
                                            onClick: () => updateSchema({ ...schema, should_sync: false }),
                                        },
                                        secondaryButton: { children: 'Cancel' },
                                    })
                                } else {
                                    updateSchema({ ...schema, should_sync: active })
                                }
                            }}
                        />
                    </SourceEditorAction>
                </div>
                <div className="flex items-center justify-between">
                    <span className="text-muted">Current status</span>
                    {schema.status ? (
                        <Tooltip title={schema.latest_error ?? undefined} interactive={!!schema.latest_error}>
                            <LemonTag type={StatusTagSetting[schema.status] || 'default'}>{schema.status}</LemonTag>
                        </Tooltip>
                    ) : (
                        <span className="text-muted">—</span>
                    )}
                </div>
                <div className="flex items-center justify-between">
                    <span className="text-muted">Last synced</span>
                    {schema.last_synced_at ? (
                        <TZLabel time={schema.last_synced_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                    ) : (
                        <span className="text-muted">Never</span>
                    )}
                </div>
                <div className="flex items-center justify-between">
                    <span className="text-muted">Rows synced</span>
                    <span>{schema.table?.row_count?.toLocaleString() ?? '—'}</span>
                </div>
                <div className="flex items-center justify-between">
                    <span className="text-muted">Synced table</span>
                    {schema.table ? (
                        <Link
                            to={urls.sqlEditor({
                                query: defaultQuery(schema.table.name, schema.table.columns).source.query,
                            })}
                            onClick={(event) => {
                                event.preventDefault()
                                const table = schema.table!
                                newInternalTab(
                                    urls.sqlEditor({ query: defaultQuery(table.name, table.columns).source.query })
                                )
                            }}
                        >
                            <code>{schema.table.name}</code>
                        </Link>
                    ) : (
                        <span className="text-muted">Not yet synced</span>
                    )}
                </div>
            </div>
            <div className="mt-4 flex gap-2 flex-wrap">
                <SourceEditorAction source={source}>
                    {({ disabledReason }) => (
                        <Tooltip
                            title={
                                schema.sync_type === 'cdc'
                                    ? 'Trigger a CDC extraction run now.'
                                    : schema.incremental
                                      ? 'Sync incremental data since the last run.'
                                      : 'Sync all data.'
                            }
                        >
                            <LemonButton
                                type="primary"
                                onClick={() => reloadSchema(schema)}
                                disabledReason={
                                    disabledReason ??
                                    (!schema.sync_type
                                        ? 'Set up the sync method first'
                                        : schema.status === 'Running'
                                          ? 'A sync is already running'
                                          : undefined)
                                }
                            >
                                {schema.sync_type === 'cdc' ? 'Sync CDC now' : 'Sync now'}
                            </LemonButton>
                        </Tooltip>
                    )}
                </SourceEditorAction>
                {schema.status === 'Running' && (
                    <SourceEditorAction source={source}>
                        {({ disabledReason }) => (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => cancelSchema(schema)}
                                disabledReason={disabledReason}
                            >
                                Cancel current sync
                            </LemonButton>
                        )}
                    </SourceEditorAction>
                )}
                <LemonButton type="secondary" onClick={onViewSyncHistory}>
                    View sync history
                </LemonButton>
            </div>
        </div>
    )
}

function SyncMethodSection({
    sourceId,
    source,
    schema,
}: {
    sourceId: string
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
}): JSX.Element {
    // Incremental fields + saving both go through schemaSceneLogic — deliberately NOT
    // syncMethodModalLogic, which connects sourceManagementLogic and would mount + poll the full
    // sources list (the heavy `external_data_sources` fetch this page is meant to avoid).
    const logic = schemaSceneLogic({ sourceId, schemaId: schema.id })
    const { schemaIncrementalFields, schemaIncrementalFieldsLoading } = useValues(logic)
    const { loadSchemaIncrementalFields, loadSchema } = useActions(logic)

    const formRef = useRef<SyncMethodFormHandle>(null)
    const [saveDisabledReason, setSaveDisabledReason] = useState<string | undefined>()
    const [saving, setSaving] = useState(false)

    const { disabledReason: accessDisabledReason } = useSourceEditorAccess(source)

    // Load incremental fields only when the schema id changes. We intentionally exclude the kea
    // action refs from the deps — if they aren't stable, the effect would re-fire on every parent
    // re-render, reset `schemaIncrementalFields` to null, unmount the form, and blow away the
    // user's in-progress radio/field selections.
    useEffect(() => {
        loadSchemaIncrementalFields(schema.id)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [schema.id])

    const loading = schemaIncrementalFieldsLoading || !schemaIncrementalFields

    const persistSyncMethod = async (
        syncType: ExternalDataSourceSchema['sync_type'],
        incrementalField: string | null,
        incrementalFieldType: string | null,
        primaryKeyColumns: string[] | null,
        cdcTableMode?: 'consolidated' | 'cdc_only' | 'both',
        incrementalFieldLookbackSeconds?: number | null
    ): Promise<void> => {
        const noIncrementalField = syncType === 'full_refresh' || syncType === 'cdc' || syncType === 'xmin'

        const applyUpdate = async (): Promise<void> => {
            setSaving(true)
            try {
                await api.externalDataSchemas.update(schema.id, {
                    should_sync: true,
                    sync_type: syncType,
                    incremental_field: noIncrementalField ? null : incrementalField,
                    incremental_field_type: noIncrementalField ? null : incrementalFieldType,
                    incremental_field_lookback_seconds:
                        syncType === 'incremental' ? (incrementalFieldLookbackSeconds ?? null) : null,
                    primary_key_columns: syncType === 'incremental' ? (primaryKeyColumns ?? null) : null,
                    ...(syncType === 'cdc' && cdcTableMode ? { cdc_table_mode: cdcTableMode } : {}),
                })
                lemonToast.success('Sync method saved')
                loadSchema()
            } catch (e: any) {
                lemonToast.error(e?.message || "Can't save sync method at this time")
            } finally {
                setSaving(false)
            }
        }

        // Switching to or from xmin changes the table's physical schema (the `_ph_xmin` control
        // column), so the backend rebuilds the table from scratch. Warn before discarding the data.
        const crossesXminBoundary = syncType === 'xmin' || schema.sync_type === 'xmin'
        if (crossesXminBoundary && syncType !== schema.sync_type && schema.last_synced_at) {
            LemonDialog.open({
                title: 'Switching sync method requires a full resync',
                content: (
                    <div className="text-sm text-secondary deprecated-space-y-2">
                        <p>
                            Switching <strong>{schema.table?.name ?? schema.name}</strong> from{' '}
                            <strong>{SyncTypeLabelMap[schema.sync_type ?? 'full_refresh']}</strong> to{' '}
                            <strong>{SyncTypeLabelMap[syncType ?? 'full_refresh']}</strong> changes the table's
                            structure, so it will be deleted and resynced from scratch.
                        </p>
                        <p>The existing synced data is replaced. This can take a while for large tables.</p>
                    </div>
                ),
                primaryButton: { children: 'Resync now', onClick: () => void applyUpdate() },
                secondaryButton: { children: 'Cancel', type: 'tertiary' },
            })
            return
        }

        await applyUpdate()
    }

    return (
        <div>
            <SectionHeader
                title="Sync method"
                description="How this schema is synced from the source — incremental, full refresh, CDC, append, or webhook."
            />
            <div className="border rounded p-4 bg-surface-primary">
                {loading && (
                    <div className="deprecated-space-y-2">
                        <LemonSkeleton className="w-1/2 h-4" />
                        <LemonSkeleton.Row repeat={3} />
                    </div>
                )}
                {!loading && schemaIncrementalFields && (
                    <fieldset disabled={!!accessDisabledReason}>
                        <SyncMethodForm
                            ref={formRef}
                            hideFooter
                            onSaveDisabledReasonChange={setSaveDisabledReason}
                            saveButtonIsLoading={saving}
                            schema={{
                                table: schema.name,
                                should_sync: schema.should_sync,
                                description: schema.description,
                                should_sync_default: schema.should_sync_default ?? true,
                                sync_type: schema.sync_type,
                                sync_time_of_day: schema.sync_time_of_day ?? null,
                                incremental_field: schema.incremental_field ?? null,
                                incremental_field_type: schema.incremental_field_type ?? null,
                                incremental_field_lookback_seconds: schema.incremental_field_lookback_seconds ?? null,
                                incremental_available: schemaIncrementalFields.incremental_available,
                                append_available: schemaIncrementalFields.append_available,
                                cdc_available: schemaIncrementalFields.cdc_available,
                                xmin_available: schemaIncrementalFields.xmin_available,
                                cdc_table_mode: schema.cdc_table_mode,
                                incremental_fields: schemaIncrementalFields.incremental_fields,
                                supports_webhooks: schemaIncrementalFields.supports_webhooks ?? false,
                                primary_key_columns: schema.primary_key_columns ?? null,
                                available_columns: [],
                                detected_primary_keys: null,
                            }}
                            availableColumns={schemaIncrementalFields.available_columns ?? []}
                            detectedPrimaryKeys={schemaIncrementalFields.detected_primary_keys ?? null}
                            primaryKeyLocked={!!schema.table}
                            onClose={() => {}}
                            onSave={persistSyncMethod}
                        />
                    </fieldset>
                )}
            </div>
            {!loading && schemaIncrementalFields && (
                <div className="mt-4 flex justify-end">
                    <LemonButton
                        type="primary"
                        loading={saving}
                        disabledReason={accessDisabledReason ?? saveDisabledReason}
                        onClick={() => formRef.current?.triggerSave()}
                    >
                        Save
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function ColumnsAndRowFiltersSection({
    source,
    schema,
    updateSchema,
    resyncSchema,
    refreshSchemas,
    refreshingSchemas,
    supportsRowFilters,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    updateSchema: (schema: ExternalDataSourceSchema) => void
    resyncSchema: (schema: ExternalDataSourceSchema) => void
    refreshSchemas: () => void
    refreshingSchemas: boolean
    supportsRowFilters: boolean
}): JSX.Element {
    const available = schema.available_columns ?? []
    const hasAvailableColumns = available.length > 0

    // Plain value, not the render-prop form of SourceEditorAction: a fresh inline render-prop on
    // every edit would remount the editors and wipe their drafts. See useSourceEditorAccess's docstring.
    const { disabledReason: editorDisabledReason } = useSourceEditorAccess(source)

    // Both editors run in `hideActions` mode and report edits up here, so one Save commits both.
    const [draftColumns, setDraftColumns] = useState<string[] | null>(schema.enabled_columns ?? null)
    const [draftRowFilters, setDraftRowFilters] = useState<RowFilter[] | null>(schema.row_filters ?? null)

    // Reset drafts on schema switch or when server values change (e.g. reload after save).
    // Keyed on content so unrelated re-renders don't wipe edits.
    useEffect(() => {
        setDraftColumns(schema.enabled_columns ?? null)
        setDraftRowFilters(schema.row_filters ?? null)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [schema.id, JSON.stringify(schema.enabled_columns ?? null), JSON.stringify(schema.row_filters ?? null)])

    const alwaysRetained = new Set<string>([
        ...(schema.primary_key_columns ?? []),
        ...(schema.incremental_field ? [schema.incremental_field] : []),
    ])
    const syncedCount = draftColumns ? new Set([...draftColumns, ...alwaysRetained]).size : available.length
    const columnsSummary = !draftColumns
        ? `Syncing all ${available.length || 'discovered'} columns`
        : `Syncing ${syncedCount} of ${available.length} columns`

    const filterCount = draftRowFilters?.length ?? 0
    const rowFiltersSummary =
        filterCount === 0 ? 'Syncing all rows' : `${filterCount} ${filterCount === 1 ? 'filter' : 'filters'} active`

    const rowFilterErrors = validateRowFilters(draftRowFilters ?? [], { availableColumns: available })
    const hasRowFilterErrors = Object.keys(rowFilterErrors).length > 0

    const isDirty =
        !sameColumns(draftColumns, schema.enabled_columns ?? null, available) ||
        JSON.stringify(draftRowFilters ?? null) !== JSON.stringify(schema.row_filters ?? null)

    const commit = (resyncAfter: boolean): void => {
        const next = { ...schema, enabled_columns: draftColumns, row_filters: draftRowFilters }
        if (resyncAfter) {
            // Bypass the bulk-update debounce so resync reads the new config from the DB, not the
            // stale one a still-queued PATCH hasn't written yet.
            void api.externalDataSchemas
                .update(schema.id, { enabled_columns: draftColumns, row_filters: draftRowFilters })
                .then(() => {
                    updateSchema(next)
                    resyncSchema(next)
                    lemonToast.success('Saved — full resync queued')
                })
                .catch((e: any) => {
                    lemonToast.error(e?.message || "Can't save at this time")
                })
            return
        }
        updateSchema(next)
        lemonToast.success('Saved')
    }

    const handleSave = (): void => {
        const syncType = schema.sync_type
        const added = getAddedColumns(schema.enabled_columns ?? null, draftColumns, available)
        const requiresPrompt =
            !!schema.last_synced_at &&
            (syncType === 'incremental' || syncType === 'append' || syncType === 'cdc') &&
            added.length > 0

        if (!requiresPrompt) {
            commit(false)
            return
        }

        LemonDialog.open({
            title: 'New columns added to a partial-sync table',
            description: (
                <div className="flex flex-col gap-2">
                    <span>
                        You added {added.length === 1 ? '1 column' : `${added.length} columns`} to a{' '}
                        <code>{syncType}</code> table. Existing rows will be backfilled with <code>NULL</code> for the
                        new column(s) unless you full-resync the table.
                    </span>
                    {added.length <= 6 && (
                        <span className="text-xs text-muted">Added: {added.map((c) => `"${c}"`).join(', ')}</span>
                    )}
                </div>
            ),
            primaryButton: { children: 'Full resync now', onClick: () => commit(true) },
            secondaryButton: { children: 'Sync forward only', onClick: () => commit(false) },
        })
    }

    return (
        <div className="flex flex-col gap-6">
            <div>
                <SectionHeader
                    title="Columns"
                    description="Choose which columns from this table get synced. Primary keys and the active incremental field are always synced."
                />
                <div className="border rounded p-4 bg-surface-primary flex flex-col gap-3">
                    {!hasAvailableColumns ? (
                        <div className="flex flex-col items-center gap-2 text-center text-muted-alt py-6">
                            <span className="text-sm">
                                {!schema.last_synced_at
                                    ? 'No columns discovered yet for this schema — they will appear after the first successful sync.'
                                    : 'No columns discovered yet for this schema.'}
                            </span>
                            <SourceEditorAction source={source}>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    loading={refreshingSchemas}
                                    onClick={() => refreshSchemas()}
                                >
                                    Pull new schemas
                                </LemonButton>
                            </SourceEditorAction>
                        </div>
                    ) : (
                        <>
                            <span className="text-sm text-secondary">{columnsSummary}</span>
                            <fieldset disabled={!!editorDisabledReason}>
                                <ColumnSelectionPicker hideActions schema={schema} onChange={setDraftColumns} />
                            </fieldset>
                        </>
                    )}
                </div>
            </div>

            {supportsRowFilters && source?.access_method !== 'direct' && schema.sync_type !== 'cdc' && (
                <div>
                    <SectionHeader
                        title="Row filters"
                        description="Sync only rows that match these conditions. Filters are ANDed together and applied on the next sync — they don't remove rows already synced."
                    />
                    <div className="border rounded p-4 bg-surface-primary flex flex-col gap-3">
                        {!hasAvailableColumns ? (
                            <div className="text-sm text-muted-alt py-2 text-center">
                                No columns discovered yet — pull schemas from the Columns section above to add row
                                filters.
                            </div>
                        ) : (
                            <>
                                <span className="text-sm text-secondary">{rowFiltersSummary}</span>
                                <fieldset disabled={!!editorDisabledReason}>
                                    <RowFilterEditor hideActions schema={schema} onChange={setDraftRowFilters} />
                                </fieldset>
                            </>
                        )}
                    </div>
                </div>
            )}

            {hasAvailableColumns && (
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        disabledReason={
                            editorDisabledReason ??
                            (hasRowFilterErrors
                                ? 'Fix the highlighted row filters first'
                                : !isDirty
                                  ? 'No changes to save'
                                  : undefined)
                        }
                    >
                        Save
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

function ScheduleSection({
    sourceId,
    source,
    schema,
    isProjectTime,
    setIsProjectTime,
}: {
    sourceId: string
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    isProjectTime: boolean
    setIsProjectTime: (v: boolean) => void
}): JSX.Element {
    const { loadSchema } = useActions(schemaSceneLogic({ sourceId, schemaId: schema.id }))
    const isCdc = schema.sync_type === 'cdc'
    const frequencyOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = allowedSyncFrequencies(
        schema.sync_type
    ).map((value) => ({ value, label: SyncFrequencyLabelMap[value] }))

    const [draftFrequency, setDraftFrequency] = useState<DataWarehouseSyncInterval>(
        schema.sync_frequency || (isCdc ? '5min' : '6hour')
    )
    const [draftSyncTimeOfDay, setDraftSyncTimeOfDay] = useState<string | null>(schema.sync_time_of_day ?? null)
    const [saving, setSaving] = useState(false)
    const { disabledReason: accessDisabledReason } = useSourceEditorAccess(source)

    const serverFrequency = schema.sync_frequency || (isCdc ? '5min' : '6hour')
    const serverSyncTimeOfDay = schema.sync_time_of_day ?? null

    // Reset the draft when the user navigates to a different schema or when the server values
    // change (e.g. after the sync type switches between CDC and non-CDC, which flips the default
    // frequency).
    useEffect(() => {
        setDraftFrequency(serverFrequency)
        setDraftSyncTimeOfDay(serverSyncTimeOfDay)
    }, [schema.id, serverFrequency, serverSyncTimeOfDay])

    const isDirty = draftFrequency !== serverFrequency || draftSyncTimeOfDay !== serverSyncTimeOfDay

    const handleSave = async (): Promise<void> => {
        setSaving(true)
        try {
            await api.externalDataSources.bulkUpdateSchemas(sourceId, [
                {
                    id: schema.id,
                    should_sync: schema.should_sync,
                    sync_type: schema.sync_type,
                    incremental_field: schema.incremental_field,
                    incremental_field_type: schema.incremental_field_type,
                    sync_frequency: draftFrequency,
                    sync_time_of_day: draftSyncTimeOfDay,
                    cdc_table_mode: schema.cdc_table_mode,
                },
            ])
            lemonToast.success('Schedule saved')
            loadSchema()
        } catch (e: any) {
            lemonToast.error(e?.message || "Can't save schedule at this time")
        } finally {
            setSaving(false)
        }
    }

    return (
        <div>
            <SectionHeader
                title="Schedule"
                description="Configure how often this schema is synced. Changes are only applied when you click Save."
            />
            <div className="border rounded p-4 bg-surface-primary flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <span>Sync frequency</span>
                    <span className="text-xs text-muted max-w-md">
                        How often PostHog pulls new data from the source. Shorter intervals mean fresher data but more
                        load on the source database
                        {isCdc ? ' — CDC supports sub-minute replication for near-real-time syncs.' : '.'}
                    </span>
                    <LemonSelect
                        fullWidth
                        disabledReason={accessDisabledReason}
                        value={draftFrequency}
                        onChange={(value) => setDraftFrequency(value as DataWarehouseSyncInterval)}
                        options={frequencyOptions}
                    />
                </div>
                <AnchorTimeField
                    source={source}
                    schema={schema}
                    draftFrequency={draftFrequency}
                    draftSyncTimeOfDay={draftSyncTimeOfDay}
                    setDraftSyncTimeOfDay={setDraftSyncTimeOfDay}
                    isProjectTime={isProjectTime}
                    setIsProjectTime={setIsProjectTime}
                />
            </div>
            <div className="mt-4 flex justify-end">
                <LemonButton
                    type="primary"
                    loading={saving}
                    onClick={handleSave}
                    disabledReason={accessDisabledReason ?? (!isDirty ? 'No changes to save' : undefined)}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}

function AnchorTimeField({
    source,
    schema,
    draftFrequency,
    draftSyncTimeOfDay,
    setDraftSyncTimeOfDay,
    isProjectTime,
    setIsProjectTime,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    draftFrequency: DataWarehouseSyncInterval
    draftSyncTimeOfDay: string | null
    setDraftSyncTimeOfDay: (value: string | null) => void
    isProjectTime: boolean
    setIsProjectTime: (v: boolean) => void
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { disabledReason: accessDisabledReason } = useSourceEditorAccess(source)

    const isSyncTimeSet = draftSyncTimeOfDay !== null
    const utcTime = draftSyncTimeOfDay || '00:00:00'
    const localTime = isProjectTime
        ? dayjs
              .utc(`${dayjs().format('YYYY-MM-DD')}T${utcTime}`)
              .local()
              .tz(currentTeam?.timezone || 'UTC')
              .format('HH:mm:00')
        : utcTime

    const disabledReasonForInput = useCallback((): string | undefined => {
        if (!schema.should_sync && !isSyncTimeSet) {
            return 'Enable syncing and anchor times to set anchor time'
        }

        if (!schema.should_sync) {
            return 'Enable syncing to set anchor time'
        }

        if (!isSyncTimeSet) {
            return 'Enable anchor times to set anchor time'
        }

        if (['1min', '5min', '15min', '30min', '1hour'].indexOf(draftFrequency) !== -1) {
            return 'Anchor time does not apply to sync intervals one hour or less'
        }
        return undefined
    }, [isSyncTimeSet, schema.should_sync, draftFrequency])

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-start justify-between gap-4">
                <div className="flex flex-col">
                    <span>Anchor time</span>
                    <span className="text-xs text-muted max-w-md">
                        Pin the sync schedule so runs start at a predictable time each day (useful for coordinating with
                        downstream jobs). Only applies to intervals longer than one hour.
                    </span>
                </div>
                {currentTeam?.timezone !== 'UTC' && currentTeam?.timezone !== 'GMT' && (
                    <div className="flex items-center gap-1 text-xs shrink-0">
                        <span>UTC</span>
                        <LemonSwitch size="xsmall" checked={isProjectTime} onChange={setIsProjectTime} />
                        <span>{currentTeam?.timezone || 'UTC'}</span>
                    </div>
                )}
            </div>
            <div className="flex items-center gap-2">
                <LemonSwitch
                    checked={isSyncTimeSet}
                    disabledReason={
                        accessDisabledReason ?? (!schema.should_sync ? 'Enable syncing to set anchor time' : undefined)
                    }
                    onChange={(checked) => {
                        setDraftSyncTimeOfDay(checked ? (isProjectTime ? localTime : utcTime) : null)
                    }}
                />
                <LemonInput
                    className="flex-1"
                    type="time"
                    disabledReason={accessDisabledReason ?? disabledReasonForInput()}
                    value={isSyncTimeSet ? localTime.substring(0, 5) : undefined}
                    onChange={(value) => {
                        const newValue = `${value}:00`
                        const utcValue = isProjectTime
                            ? dayjs(`${dayjs().format('YYYY-MM-DD')}T${newValue}`)
                                  .tz(currentTeam?.timezone || 'UTC')
                                  .utc()
                                  .format('HH:mm:00')
                            : newValue
                        setDraftSyncTimeOfDay(utcValue)
                    }}
                    suffix={
                        isSyncTimeSet && schema.should_sync ? (
                            <Tooltip title={syncAnchorIntervalToHumanReadable(utcTime, draftFrequency)}>
                                <IconInfo className="text-muted-alt" />
                            </Tooltip>
                        ) : undefined
                    }
                />
            </div>
        </div>
    )
}

function DangerZoneSection({
    source,
    schema,
    resyncSchema,
    resyncingSchema,
    deleteTable,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    resyncSchema: (schema: ExternalDataSourceSchema) => void
    resyncingSchema: boolean
    deleteTable: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const hasFullCdcResync = schema.sync_type === 'cdc'
    const hasDeleteAndResync = schema.incremental || schema.sync_type === 'webhook' || schema.sync_type === 'xmin'
    const canDeleteTable = !!schema.table

    if (!hasFullCdcResync && !hasDeleteAndResync && !canDeleteTable) {
        return (
            <div>
                <SectionHeader title="Danger zone" />
                <div className="border border-dashed rounded p-4 bg-surface-primary text-muted">
                    No destructive actions are available for this schema yet.
                </div>
            </div>
        )
    }

    return (
        <div>
            <SectionHeader
                title="Danger zone"
                description="Destructive actions that rebuild or remove data. Use only if you understand the impact."
            />
            <div className="border border-danger/40 rounded p-4 bg-surface-primary flex flex-col gap-2">
                <SourceEditorAction source={source}>
                    {({ disabledReason }) => (
                        <>
                            {hasFullCdcResync && (
                                <Tooltip title="Re-snapshot the full table and replay all CDC changes on top. Use this to recover from a corrupted or out-of-sync table.">
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={() => {
                                            const hasCdcTable =
                                                schema.cdc_table_mode === 'cdc_only' || schema.cdc_table_mode === 'both'
                                            LemonDialog.open({
                                                title: 'Full resync — all existing data will be replaced',
                                                content: (
                                                    <div className="text-sm text-secondary space-y-2">
                                                        <p>
                                                            This will re-snapshot the entire table from the source
                                                            database. All rows currently in the{' '}
                                                            <strong>{schema.table?.name ?? schema.name}</strong> table
                                                            will be replaced with the new snapshot.
                                                        </p>
                                                        {hasCdcTable && (
                                                            <p>
                                                                The{' '}
                                                                <strong>
                                                                    {(schema.table?.name ?? schema.name) + '_cdc'}
                                                                </strong>{' '}
                                                                history table will also be reset — all change history
                                                                will be lost and replaced with the new snapshot as the
                                                                starting point.
                                                            </p>
                                                        )}
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Full resync',
                                                    status: 'danger',
                                                    onClick: () => resyncSchema(schema),
                                                },
                                                secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                            })
                                        }}
                                        loading={resyncingSchema}
                                        disabledReason={disabledReason}
                                    >
                                        Full resync
                                    </LemonButton>
                                </Tooltip>
                            )}
                            {hasDeleteAndResync && (
                                <Tooltip title="Completely resync data by deleting the existing table and re-importing. Only recommended if there is an issue with data quality in previously imported data.">
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={() => resyncSchema(schema)}
                                        loading={resyncingSchema}
                                        disabledReason={disabledReason}
                                    >
                                        Delete table and resync
                                    </LemonButton>
                                </Tooltip>
                            )}
                            {canDeleteTable && (
                                <Tooltip
                                    title={`Delete this table from PostHog. ${
                                        source?.source_type
                                            ? `This will not delete the data in ${source.source_type}`
                                            : ''
                                    }`}
                                >
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: `Delete ${schema.table?.name ?? schema.name} from PostHog?`,
                                                description: source?.source_type
                                                    ? `The data in ${source.source_type} will not be touched.`
                                                    : undefined,
                                                primaryButton: {
                                                    children: 'Delete',
                                                    status: 'danger',
                                                    onClick: () => deleteTable(schema),
                                                },
                                                secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                            })
                                        }}
                                        disabledReason={disabledReason}
                                    >
                                        Delete table from PostHog
                                    </LemonButton>
                                </Tooltip>
                            )}
                        </>
                    )}
                </SourceEditorAction>
            </div>
        </div>
    )
}

const DESCRIPTION_SOURCE_LABELS: Record<string, string> = {
    native_comment: 'From source',
    ai_generated: 'AI generated',
    user_edited: 'Edited',
}

function DescriptionSourceTag({ source }: { source?: string }): JSX.Element | null {
    if (!source) {
        return null
    }
    return (
        <LemonTag type={source === 'user_edited' ? 'success' : 'muted'} size="small">
            {DESCRIPTION_SOURCE_LABELS[source] ?? source}
        </LemonTag>
    )
}

function DescriptionRow({
    columnName,
    label,
    dataType,
    description,
    source,
    saving,
    onSave,
}: {
    columnName: string
    label: string
    dataType?: string
    description: string
    source?: string
    saving: boolean
    onSave: (columnName: string, description: string) => void
}): JSX.Element {
    const [value, setValue] = useState(description)
    // Keep local state in sync when the annotation reloads (e.g. after a save or AI enrichment).
    useEffect(() => setValue(description), [description])
    const dirty = value !== description

    return (
        <div className="flex items-center gap-2 py-1.5 border-b border-border last:border-b-0">
            <div className="w-1/4 min-w-0">
                <code className="text-xs">{label}</code>
                {dataType && <span className="text-muted text-xs ml-2">{dataType}</span>}
            </div>
            <LemonInput
                className="flex-1"
                size="small"
                value={value}
                onChange={setValue}
                placeholder="Describe what this means…"
                onPressEnter={() => dirty && onSave(columnName, value)}
            />
            <DescriptionSourceTag source={source} />
            <LemonButton
                size="small"
                type="secondary"
                onClick={() => onSave(columnName, value)}
                loading={saving}
                disabledReason={!dirty ? 'No changes to save' : undefined}
            >
                Save
            </LemonButton>
        </div>
    )
}

function DescriptionsSection({ schema }: { schema: ExternalDataSourceSchema }): JSX.Element {
    const tableId = schema.table?.id

    if (!tableId) {
        return (
            <div>
                <SectionHeader title="Descriptions" />
                <div className="border border-dashed rounded p-4 bg-surface-primary text-muted">
                    Sync this table at least once to add descriptions for its columns.
                </div>
            </div>
        )
    }

    return <DescriptionsSectionContent tableId={tableId} columns={schema.available_columns ?? []} />
}

function DescriptionsSectionContent({
    tableId,
    columns,
}: {
    tableId: string
    columns: { name: string; data_type?: string; is_nullable?: boolean }[]
}): JSX.Element {
    const logic = columnAnnotationsLogic({ tableId })
    const { annotationByColumn, annotationsLoading, savingColumn } = useValues(logic)
    const { saveDescription } = useActions(logic)

    const tableAnnotation = annotationByColumn['']

    return (
        <div>
            <SectionHeader
                title="Descriptions"
                description="Describe what this table and its columns mean. These descriptions help PostHog AI write correct queries against your data. Descriptions are generated automatically (from the source's documentation or AI) and anything you edit here is preserved."
            />
            <div className="border rounded p-4 bg-surface-primary">
                <DescriptionRow
                    columnName=""
                    label="(whole table)"
                    description={tableAnnotation?.description ?? ''}
                    source={tableAnnotation?.description_source}
                    saving={savingColumn === ''}
                    onSave={saveDescription}
                />
                {annotationsLoading && columns.length === 0 ? (
                    <LemonSkeleton className="w-full h-8 mt-2" />
                ) : columns.length === 0 ? (
                    <div className="text-muted text-sm mt-2">No columns discovered yet for this schema.</div>
                ) : (
                    columns.map((column) => {
                        const annotation = annotationByColumn[column.name]
                        return (
                            <DescriptionRow
                                key={column.name}
                                columnName={column.name}
                                label={column.name}
                                dataType={column.data_type}
                                description={annotation?.description ?? ''}
                                source={annotation?.description_source}
                                saving={savingColumn === column.name}
                                onSave={saveDescription}
                            />
                        )
                    })
                )}
            </div>
        </div>
    )
}
