import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSelectOption,
    LemonSkeleton,
    LemonSwitch,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { DataWarehouseSyncInterval, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { SyncMethodForm } from 'products/data_warehouse/frontend/shared/components/forms/SyncMethodForm'
import { SourceEditorAction } from 'products/data_warehouse/frontend/shared/components/SourceEditorAction'
import {
    StatusTagSetting,
    SyncTypeLabelMap,
    defaultQuery,
    syncAnchorIntervalToHumanReadable,
} from 'products/data_warehouse/frontend/utils'

import { syncMethodModalLogic } from '../SourceScene/syncMethodModalLogic'
import { sourceSettingsLogic } from '../SourceScene/tabs/sourceSettingsLogic'

export function ConfigurationTab({
    sourceId,
    schema,
    source,
}: {
    sourceId: string
    schema: ExternalDataSourceSchema
    source: ExternalDataSource | null
}): JSX.Element {
    const logic = sourceSettingsLogic({ id: sourceId })
    const { isProjectTime } = useValues(logic)
    const { setIsProjectTime, updateSchema, reloadSchema, resyncSchema, cancelSchema, deleteTable } = useActions(logic)

    return (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="flex flex-col gap-4 lg:col-span-1">
                <StatusSection schema={schema} />
                <EnabledSection source={source} schema={schema} updateSchema={updateSchema} />
                <ScheduleSection
                    source={source}
                    schema={schema}
                    isProjectTime={isProjectTime}
                    setIsProjectTime={setIsProjectTime}
                    updateSchema={updateSchema}
                />
            </div>
            <div className="flex flex-col gap-4 lg:col-span-2">
                <SyncMethodSection source={source} schema={schema} updateSchema={updateSchema} />
                <ActionsSection
                    source={source}
                    schema={schema}
                    reloadSchema={reloadSchema}
                    resyncSchema={resyncSchema}
                    cancelSchema={cancelSchema}
                    deleteTable={deleteTable}
                />
            </div>
        </div>
    )
}

function StatusSection({ schema }: { schema: ExternalDataSourceSchema }): JSX.Element {
    return (
        <SceneSection title="Status" titleSize="sm">
            <div className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
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
        </SceneSection>
    )
}

function EnabledSection({
    source,
    schema,
    updateSchema,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    return (
        <SceneSection
            title="Enabled"
            description="When disabled, this schema will not be synced on the configured schedule."
            titleSize="sm"
        >
            <div className="border rounded p-3 bg-surface-primary">
                <SourceEditorAction source={source}>
                    <LemonSwitch
                        bordered={false}
                        disabledReason={schema.sync_type === null ? 'You must set up the sync method first' : undefined}
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
                                                remove it from the replication publication. Changes made while disabled
                                                will be permanently lost.
                                            </p>
                                            <p>
                                                Re-enabling this table will require a <strong>full resync</strong> to
                                                ensure data consistency.
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
        </SceneSection>
    )
}

function ScheduleSection({
    source,
    schema,
    isProjectTime,
    setIsProjectTime,
    updateSchema,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    isProjectTime: boolean
    setIsProjectTime: (v: boolean) => void
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const isCdc = schema.sync_type === 'cdc'
    const cdcOnlyOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = [{ value: '1min', label: '1 min' }]
    const standardOptions: LemonSelectOption<DataWarehouseSyncInterval>[] = [
        { value: '5min', label: '5 mins' },
        { value: '15min', label: '15 mins' },
        { value: '30min', label: '30 mins' },
        { value: '1hour', label: '1 hour' },
        { value: '6hour', label: '6 hours' },
        { value: '12hour', label: '12 hours' },
        { value: '24hour', label: 'Daily' },
        { value: '7day', label: 'Weekly' },
        { value: '30day', label: 'Monthly' },
    ]

    return (
        <SceneSection title="Schedule" titleSize="sm">
            <div className="border rounded p-3 bg-surface-primary flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted">Sync frequency</span>
                    <SourceEditorAction source={source}>
                        {({ disabledReason: accessDisabledReason }) => (
                            <LemonSelect
                                fullWidth
                                disabledReason={
                                    accessDisabledReason ??
                                    (!schema.should_sync ? 'Enable syncing to set frequency' : undefined)
                                }
                                value={schema.sync_frequency || (isCdc ? '5min' : '6hour')}
                                onChange={(value) =>
                                    updateSchema({ ...schema, sync_frequency: value as DataWarehouseSyncInterval })
                                }
                                options={isCdc ? [...cdcOnlyOptions, ...standardOptions] : standardOptions}
                            />
                        )}
                    </SourceEditorAction>
                </div>
                <AnchorTimeField
                    source={source}
                    schema={schema}
                    isProjectTime={isProjectTime}
                    setIsProjectTime={setIsProjectTime}
                    updateSchema={updateSchema}
                />
            </div>
        </SceneSection>
    )
}

function AnchorTimeField({
    source,
    schema,
    isProjectTime,
    setIsProjectTime,
    updateSchema,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    isProjectTime: boolean
    setIsProjectTime: (v: boolean) => void
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const [isSyncTimeSet, setIsSyncTimeSet] = useState(!!schema.sync_time_of_day)

    const utcTime = schema.sync_time_of_day || '00:00:00'
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
        if (
            schema.sync_frequency === '5min' ||
            schema.sync_frequency === '30min' ||
            schema.sync_frequency === '1hour'
        ) {
            return 'Anchor time does not apply to sync intervals one hour or less'
        }
        return undefined
    }, [isSyncTimeSet, schema.should_sync, schema.sync_frequency])

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
                <span className="text-xs text-muted">Anchor time</span>
                {currentTeam?.timezone !== 'UTC' && currentTeam?.timezone !== 'GMT' && (
                    <div className="flex items-center gap-1 text-xs">
                        <span>UTC</span>
                        <LemonSwitch size="xsmall" checked={isProjectTime} onChange={setIsProjectTime} />
                        <span>{currentTeam?.timezone || 'UTC'}</span>
                    </div>
                )}
            </div>
            <SourceEditorAction source={source}>
                {({ disabledReason: accessDisabledReason }) => (
                    <div className="flex items-center gap-2">
                        <LemonSwitch
                            checked={isSyncTimeSet}
                            disabledReason={
                                accessDisabledReason ??
                                (!schema.should_sync ? 'Enable syncing to set anchor time' : undefined)
                            }
                            onChange={(checked) => {
                                setIsSyncTimeSet(checked)
                                updateSchema({
                                    ...schema,
                                    sync_time_of_day: checked ? (isProjectTime ? localTime : utcTime) : null,
                                })
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
                                updateSchema({ ...schema, sync_time_of_day: utcValue })
                            }}
                            suffix={
                                isSyncTimeSet && schema.should_sync ? (
                                    <Tooltip title={syncAnchorIntervalToHumanReadable(utcTime, schema.sync_frequency)}>
                                        <IconInfo className="text-muted-alt" />
                                    </Tooltip>
                                ) : undefined
                            }
                        />
                    </div>
                )}
            </SourceEditorAction>
        </div>
    )
}

function SyncMethodSection({
    source,
    schema,
    updateSchema,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const { openSyncMethodModal } = useActions(syncMethodModalLogic({ schema }))

    return (
        <SceneSection
            title="Sync method"
            description="How this schema is synced from the source — incremental, full refresh, CDC, append, or webhook."
            titleSize="sm"
        >
            <div className="border rounded p-3 bg-surface-primary flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    {schema.sync_type ? (
                        <LemonTag type="primary">{SyncTypeLabelMap[schema.sync_type]}</LemonTag>
                    ) : (
                        <span className="text-muted">Not configured</span>
                    )}
                    {schema.incremental_field && (
                        <span className="text-xs text-muted">
                            Field: <code>{schema.incremental_field}</code>
                        </span>
                    )}
                </div>
                <SourceEditorAction source={source}>
                    <LemonButton
                        type={schema.sync_type ? 'secondary' : 'primary'}
                        onClick={() => openSyncMethodModal(schema)}
                    >
                        {schema.sync_type ? 'Edit' : 'Set up'}
                    </LemonButton>
                </SourceEditorAction>
            </div>
            <SyncMethodModal schema={schema} updateSchema={updateSchema} />
        </SceneSection>
    )
}

function ActionsSection({
    source,
    schema,
    reloadSchema,
    resyncSchema,
    cancelSchema,
    deleteTable,
}: {
    source: ExternalDataSource | null
    schema: ExternalDataSourceSchema
    reloadSchema: (schema: ExternalDataSourceSchema) => void
    resyncSchema: (schema: ExternalDataSourceSchema) => void
    cancelSchema: (schema: ExternalDataSourceSchema) => void
    deleteTable: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    return (
        <SceneSection
            title="Actions"
            description="Run a sync now, recover from issues with a full resync, or remove the synced table."
            titleSize="sm"
        >
            <div className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
                <SourceEditorAction source={source}>
                    {({ disabledReason }) => (
                        <div className="flex flex-col gap-2">
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
                                    disabledReason={disabledReason}
                                >
                                    {schema.sync_type === 'cdc' ? 'Sync CDC now' : 'Sync now'}
                                </LemonButton>
                            </Tooltip>
                            {schema.status === 'Running' && (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    onClick={() => cancelSchema(schema)}
                                    disabledReason={disabledReason}
                                >
                                    Cancel current sync
                                </LemonButton>
                            )}
                            <LemonDivider />
                            {schema.sync_type === 'cdc' && (
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
                            {(schema.incremental || schema.sync_type === 'webhook') && (
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
                            {schema.table && (
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
                        </div>
                    )}
                </SourceEditorAction>
            </div>
        </SceneSection>
    )
}

function SyncMethodModal({
    schema,
    updateSchema,
}: {
    schema: ExternalDataSourceSchema
    updateSchema: (schema: ExternalDataSourceSchema) => void
}): JSX.Element {
    const logic = syncMethodModalLogic({ schema })
    const {
        syncMethodModalIsOpen,
        currentSyncMethodModalSchema,
        schemaIncrementalFields,
        schemaIncrementalFieldsLoading,
        saveButtonIsLoading,
    } = useValues(logic)
    const { closeSyncMethodModal, loadSchemaIncrementalFields, resetSchemaIncrementalFields } = useActions(logic)

    useEffect(() => {
        if (currentSyncMethodModalSchema?.id) {
            resetSchemaIncrementalFields()
            loadSchemaIncrementalFields(currentSyncMethodModalSchema.id)
        }
    }, [currentSyncMethodModalSchema?.id, resetSchemaIncrementalFields, loadSchemaIncrementalFields])

    if (!currentSyncMethodModalSchema) {
        return <></>
    }

    const schemaLoading = schemaIncrementalFieldsLoading || !schemaIncrementalFields
    const showForm = !schemaLoading && schemaIncrementalFields

    return (
        <LemonModal
            title={
                <>
                    Sync method for{' '}
                    <span className="font-mono">
                        {currentSyncMethodModalSchema.label ?? currentSyncMethodModalSchema.name}
                    </span>
                </>
            }
            isOpen={syncMethodModalIsOpen}
            onClose={closeSyncMethodModal}
            footer={
                schemaLoading ? (
                    <>
                        <LemonSkeleton.Button />
                        <LemonSkeleton.Button />
                    </>
                ) : null
            }
        >
            {schemaLoading && (
                <div className="deprecated-space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton.Row repeat={3} />
                </div>
            )}
            {showForm && (
                <SyncMethodForm
                    saveButtonIsLoading={saveButtonIsLoading}
                    schema={{
                        table: currentSyncMethodModalSchema.name,
                        should_sync: currentSyncMethodModalSchema.should_sync,
                        description: currentSyncMethodModalSchema.description,
                        should_sync_default: currentSyncMethodModalSchema.should_sync_default ?? true,
                        sync_type: currentSyncMethodModalSchema.sync_type,
                        sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? null,
                        incremental_field: currentSyncMethodModalSchema.incremental_field ?? null,
                        incremental_field_type: currentSyncMethodModalSchema.incremental_field_type ?? null,
                        incremental_available: schemaIncrementalFields.incremental_available,
                        append_available: schemaIncrementalFields.append_available,
                        cdc_available: schemaIncrementalFields.cdc_available,
                        cdc_table_mode: currentSyncMethodModalSchema.cdc_table_mode,
                        incremental_fields: schemaIncrementalFields.incremental_fields,
                        supports_webhooks: schemaIncrementalFields?.supports_webhooks ?? false,
                        primary_key_columns: currentSyncMethodModalSchema.primary_key_columns ?? null,
                        available_columns: [],
                        detected_primary_keys: null,
                    }}
                    availableColumns={schemaIncrementalFields.available_columns ?? []}
                    detectedPrimaryKeys={schemaIncrementalFields.detected_primary_keys ?? null}
                    primaryKeyLocked={!!currentSyncMethodModalSchema.table}
                    onClose={() => {
                        resetSchemaIncrementalFields()
                        closeSyncMethodModal()
                    }}
                    onSave={(syncType, incrementalField, incrementalFieldType, primaryKeyColumns, cdcTableMode) => {
                        const noIncrementalField = syncType === 'full_refresh' || syncType === 'cdc'
                        updateSchema({
                            ...currentSyncMethodModalSchema,
                            should_sync: true,
                            sync_type: syncType,
                            incremental_field: noIncrementalField ? null : incrementalField,
                            incremental_field_type: noIncrementalField ? null : incrementalFieldType,
                            sync_time_of_day: currentSyncMethodModalSchema.sync_time_of_day ?? null,
                            primary_key_columns: syncType === 'incremental' ? (primaryKeyColumns ?? null) : null,
                            ...(syncType === 'cdc' && cdcTableMode ? { cdc_table_mode: cdcTableMode } : {}),
                        })
                        closeSyncMethodModal()
                    }}
                />
            )}
        </LemonModal>
    )
}
