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
import { dayjs } from 'lib/dayjs'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { DataWarehouseSyncInterval, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

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
    defaultQuery,
    syncAnchorIntervalToHumanReadable,
} from 'products/data_warehouse/frontend/utils'

import { syncMethodModalLogic } from '../SourceScene/syncMethodModalLogic'
import { sourceSettingsLogic } from '../SourceScene/tabs/sourceSettingsLogic'
import { SchemaConfigurationSection } from './schemaSceneLogic'

export interface ConfigurationTabProps {
    sourceId: string
    schema: ExternalDataSourceSchema
    source: ExternalDataSource | null
    section: SchemaConfigurationSection
}

export function ConfigurationTab({ sourceId, schema, source, section }: ConfigurationTabProps): JSX.Element {
    const logic = sourceSettingsLogic({ id: sourceId })
    const { isProjectTime } = useValues(logic)
    const { setIsProjectTime, updateSchema, reloadSchema, resyncSchema, cancelSchema, deleteTable } = useActions(logic)

    switch (section) {
        case 'details':
            return (
                <DetailsSection
                    source={source}
                    schema={schema}
                    reloadSchema={reloadSchema}
                    cancelSchema={cancelSchema}
                    updateSchema={updateSchema}
                />
            )
        case 'sync-method':
            return <SyncMethodSection sourceId={sourceId} source={source} schema={schema} />
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
        case 'danger-zone':
            return (
                <DangerZoneSection
                    source={source}
                    schema={schema}
                    resyncSchema={resyncSchema}
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
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    reloadSchema: (schema: ExternalDataSourceSchema) => void
    cancelSchema: (schema: ExternalDataSourceSchema) => void
    updateSchema: (schema: ExternalDataSourceSchema) => void
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
                            disabledReason={
                                schema.sync_type === null ? 'You must set up the sync method first' : undefined
                            }
                            checked={schema.should_sync}
                            label={schema.should_sync ? 'Syncing' : 'Disabled'}
                            onChange={(active) => {
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
                                    disabledReason ?? (!schema.sync_type ? 'Set up the sync method first' : undefined)
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
    // We use syncMethodModalLogic only for loading the schema's incremental fields — saving goes
    // through a direct bulkUpdateSchemas call so the logic's reset-on-success listener (used by
    // the modal flow in the new source wizard) doesn't blow the inline form back into a loading state.
    const logic = syncMethodModalLogic({ schema })
    const { schemaIncrementalFields, schemaIncrementalFieldsLoading } = useValues(logic)
    const { loadSchemaIncrementalFields } = useActions(logic)
    const { loadSource } = useActions(sourceSettingsLogic({ id: sourceId }))

    const formRef = useRef<SyncMethodFormHandle>(null)
    const [saveDisabledReason, setSaveDisabledReason] = useState<string | undefined>()
    const [saving, setSaving] = useState(false)

    const { disabledReason: accessDisabledReason } = useSourceEditorAccess(source)

    // Load incremental fields only when the schema id changes. We intentionally exclude the kea
    // action refs from the deps — if they aren't stable, the effect would re-fire on every parent
    // re-render (e.g. the 5s sourceSettingsLogic auto-refresh), reset `schemaIncrementalFields`
    // to null, unmount the form, and blow away the user's in-progress radio/field selections.
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
        cdcTableMode?: 'consolidated' | 'cdc_only' | 'both'
    ): Promise<void> => {
        const noIncrementalField = syncType === 'full_refresh' || syncType === 'cdc'
        setSaving(true)
        try {
            await api.externalDataSchemas.update(schema.id, {
                should_sync: true,
                sync_type: syncType,
                incremental_field: noIncrementalField ? null : incrementalField,
                incremental_field_type: noIncrementalField ? null : incrementalFieldType,
                primary_key_columns: syncType === 'incremental' ? (primaryKeyColumns ?? null) : null,
                ...(syncType === 'cdc' && cdcTableMode ? { cdc_table_mode: cdcTableMode } : {}),
            })
            lemonToast.success('Sync method saved')
            loadSource()
        } catch (e: any) {
            lemonToast.error(e?.message || "Can't save sync method at this time")
        } finally {
            setSaving(false)
        }
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
                                incremental_available: schemaIncrementalFields.incremental_available,
                                append_available: schemaIncrementalFields.append_available,
                                cdc_available: schemaIncrementalFields.cdc_available,
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
    const { loadSource } = useActions(sourceSettingsLogic({ id: sourceId }))
    const isCdc = schema.sync_type === 'cdc'
    const makeOption = (value: DataWarehouseSyncInterval): LemonSelectOption<DataWarehouseSyncInterval> => ({
        value,
        label: SyncFrequencyLabelMap[value],
    })
    const cdcOnlyOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = [makeOption('1min')]
    const standardOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = (
        ['5min', '15min', '30min', '1hour', '6hour', '12hour', '24hour', '7day', '30day'] as const
    ).map(makeOption)

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
            loadSource()
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
                        disabledReason={
                            accessDisabledReason ??
                            (!schema.should_sync ? 'Enable syncing to set frequency' : undefined)
                        }
                        value={draftFrequency}
                        onChange={(value) => setDraftFrequency(value as DataWarehouseSyncInterval)}
                        options={isCdc ? [...cdcOnlyOptions, ...standardOptions] : standardOptions}
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
    deleteTable,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    resyncSchema: (schema: ExternalDataSourceSchema) => void
    deleteTable: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const hasFullCdcResync = schema.sync_type === 'cdc'
    const hasDeleteAndResync = schema.incremental || schema.sync_type === 'webhook'
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
