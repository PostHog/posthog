import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ExternalDataSourceType, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    DataWarehouseSyncInterval,
    ExternalDataSchemaStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
} from '~/types'

import { splitQualifiedTableName } from 'products/data_warehouse/frontend/shared/components/forms/schemaGroupingUtils'
import { DATA_WAREHOUSE_APP_SOURCE } from 'products/data_warehouse/frontend/shared/components/metrics/DataWarehouseMetrics'
import {
    SourceEditorAction,
    useSourceEditorAccess,
} from 'products/data_warehouse/frontend/shared/components/SourceEditorAction'
import { sourceManagementLogic } from 'products/data_warehouse/frontend/shared/logics/sourceManagementLogic'
import {
    SYNC_FREQUENCY_ORDER,
    StatusTagSetting,
    SyncFrequencyLabelMap,
    SyncTypeLabelMap,
    allowedSyncFrequencies,
} from 'products/data_warehouse/frontend/utils'

import { DirectQuerySchemasTab } from './DirectQuerySchemasTab'
import { sourceSettingsLogic } from './sourceSettingsLogic'

const REVENUE_ENABLED_SOURCES: ExternalDataSourceType[] = ['Stripe']

const frequencyRank = (frequency: DataWarehouseSyncInterval | null | undefined): number =>
    frequency ? SYNC_FREQUENCY_ORDER.indexOf(frequency) : -1

export interface SchemasTabProps {
    id: string
}

export function SchemasTab({ id }: SchemasTabProps): JSX.Element {
    const logicProps = { id, availableSources: {} }

    return (
        <BindLogic logic={sourceSettingsLogic} props={logicProps}>
            <SchemasTabInner id={id} />
        </BindLogic>
    )
}

function SchemasTabInner({ id }: { id: string }): JSX.Element {
    const { source } = useValues(sourceSettingsLogic)

    const isDirectQuerySource = source?.access_method === 'direct'

    if (isDirectQuerySource) {
        return <DirectQuerySchemasTab id={id} />
    }

    return <ManagedSchemasTab id={id} />
}

function ManagedSchemasTab({ id }: { id: string }): JSX.Element {
    const {
        source,
        sourceLoading,
        filteredSchemas,
        groupedFilteredSchemas,
        showEnabledSchemasOnly,
        schemaNameFilter,
        statusFilter,
        syncMethodFilter,
        frequencyFilter,
        schemaFilterOptions,
        syncingNow,
        refreshingSchemas,
    } = useValues(sourceSettingsLogic)
    const {
        setShowEnabledSchemasOnly,
        setSchemaNameFilter,
        setStatusFilter,
        setSyncMethodFilter,
        setFrequencyFilter,
        syncNow,
        refreshSchemas,
        updateSchema,
        reloadSchema,
        resyncSchema,
        cancelSchema,
        deleteTable,
        loadJobs,
    } = useActions(sourceSettingsLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Load (and poll) jobs so the Rows synced column can show live progress for in-progress
    // syncs, before the warehouse table exists. loadJobsSuccess reschedules itself.
    useEffect(() => {
        if (source && source.access_method !== 'direct') {
            loadJobs()
        }
    }, [loadJobs, source])

    const showMetrics = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]
    // `id` is the cleaned source id; URLs use the `managed-` prefix
    const prefixedSourceId = `managed-${id}`

    return (
        <>
            <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex flex-wrap items-center gap-3 min-w-0">
                    <LemonSwitch
                        checked={showEnabledSchemasOnly}
                        onChange={setShowEnabledSchemasOnly}
                        label="Show enabled only"
                    />
                    <LemonInput
                        type="search"
                        placeholder="Filter schemas"
                        size="small"
                        value={schemaNameFilter}
                        onChange={setSchemaNameFilter}
                    />
                    <LemonSelect
                        size="small"
                        placeholder="All statuses"
                        value={statusFilter}
                        onChange={setStatusFilter}
                        options={[
                            { value: null, label: 'All statuses' },
                            ...schemaFilterOptions.statuses.map((status) => ({ value: status, label: status })),
                        ]}
                    />
                    <LemonSelect
                        size="small"
                        placeholder="All sync methods"
                        value={syncMethodFilter}
                        onChange={setSyncMethodFilter}
                        options={[
                            { value: null, label: 'All sync methods' },
                            ...schemaFilterOptions.syncMethods.map((method) => ({
                                value: method === 'none' ? 'none' : method,
                                label: method === 'none' ? 'Not set up' : SyncTypeLabelMap[method],
                            })),
                        ]}
                    />
                    <LemonSelect
                        size="small"
                        placeholder="All frequencies"
                        value={frequencyFilter}
                        onChange={setFrequencyFilter}
                        options={[
                            { value: null, label: 'All frequencies' },
                            ...schemaFilterOptions.frequencies.map((frequency) => ({
                                value: frequency,
                                label: SyncFrequencyLabelMap[frequency],
                            })),
                        ]}
                    />
                    <span className="text-muted text-sm">{pluralize(filteredSchemas.length, 'schema', 'schemas')}</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <SourceEditorAction source={source}>
                        <LemonButton
                            type="secondary"
                            loading={syncingNow}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Sync all enabled schemas?',
                                    content: (
                                        <div className="text-sm text-secondary">
                                            This will trigger a sync for all schemas you have enabled. New sync jobs
                                            will appear in the Syncs tab.
                                        </div>
                                    ),
                                    primaryButton: {
                                        children: 'Sync now',
                                        type: 'primary',
                                        onClick: () => syncNow(),
                                    },
                                    secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                })
                            }}
                            disabledReason={
                                sourceLoading
                                    ? 'Source is loading'
                                    : refreshingSchemas
                                      ? 'Schema refresh in progress'
                                      : undefined
                            }
                        >
                            Sync all enabled schemas
                        </LemonButton>
                    </SourceEditorAction>
                    <SourceEditorAction source={source}>
                        <LemonButton
                            type="secondary"
                            loading={refreshingSchemas}
                            onClick={() => refreshSchemas()}
                            disabledReason={
                                sourceLoading ? 'Source is loading' : syncingNow ? 'Sync in progress' : undefined
                            }
                        >
                            Pull new schemas
                        </LemonButton>
                    </SourceEditorAction>
                </div>
            </div>
            {groupedFilteredSchemas.length > 1 ? (
                <div className="border rounded bg-bg-light">
                    <LemonCollapse
                        multiple
                        embedded
                        defaultActiveKeys={groupedFilteredSchemas.map((group) => group.schemaName)}
                        panels={groupedFilteredSchemas.map(({ schemaName, tables }) => ({
                            key: schemaName,
                            header: (
                                <div className="flex items-center justify-between gap-3 w-full">
                                    <span className="font-semibold truncate">{schemaName}</span>
                                    <span className="text-xs text-muted-alt whitespace-nowrap">
                                        {tables.filter((schema) => schema.should_sync).length} of {tables.length}{' '}
                                        enabled
                                    </span>
                                </div>
                            ),
                            content: (
                                <ManagedSchemaTable
                                    schemas={tables}
                                    inSchemaGroup
                                    isLoading={sourceLoading}
                                    source={source}
                                    sourceId={id}
                                    prefixedSourceId={prefixedSourceId}
                                    updateSchema={updateSchema}
                                    reloadSchema={reloadSchema}
                                    resyncSchema={resyncSchema}
                                    cancelSchema={cancelSchema}
                                    deleteTable={deleteTable}
                                    showMetrics={showMetrics}
                                />
                            ),
                        }))}
                    />
                </div>
            ) : (
                <ManagedSchemaTable
                    schemas={filteredSchemas}
                    isLoading={sourceLoading}
                    source={source}
                    sourceId={id}
                    prefixedSourceId={prefixedSourceId}
                    updateSchema={updateSchema}
                    reloadSchema={reloadSchema}
                    resyncSchema={resyncSchema}
                    cancelSchema={cancelSchema}
                    deleteTable={deleteTable}
                    showMetrics={showMetrics}
                />
            )}
            {source?.source_type &&
                REVENUE_ENABLED_SOURCES.includes(source.source_type) &&
                featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] && (
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            className="mt-2"
                            tooltip="This source is feeding data into our Revenue analytics product - currently in alpha."
                            onClick={() => {
                                addProductIntentForCrossSell({
                                    from: ProductKey.DATA_WAREHOUSE,
                                    to: ProductKey.REVENUE_ANALYTICS,
                                    intent_context: ProductIntentContext.DATA_WAREHOUSE_STRIPE_SOURCE_CREATED,
                                })
                                router.actions.push(urls.revenueAnalytics())
                            }}
                        >
                            See data in Revenue analytics
                            <LemonTag className="ml-2" type="danger" size="small">
                                ALPHA
                            </LemonTag>
                        </LemonButton>
                    </div>
                )}
        </>
    )
}

interface ManagedSchemaTableProps {
    schemas: ExternalDataSourceSchema[]
    isLoading: boolean
    source: ExternalDataSource | null
    sourceId: string
    prefixedSourceId: string
    updateSchema: (schema: ExternalDataSourceSchema) => void
    reloadSchema: (schema: ExternalDataSourceSchema) => void
    resyncSchema: (schema: ExternalDataSourceSchema) => void
    cancelSchema: (schema: ExternalDataSourceSchema) => void
    deleteTable: (schema: ExternalDataSourceSchema) => void
    showMetrics: boolean
    /** Rendered inside a namespace group — the group header already shows the namespace, so strip it from row names. */
    inSchemaGroup?: boolean
}

function ManagedSchemaTable({
    schemas,
    isLoading,
    source,
    sourceId,
    prefixedSourceId,
    updateSchema,
    reloadSchema,
    resyncSchema,
    cancelSchema,
    deleteTable,
    showMetrics,
    inSchemaGroup = false,
}: ManagedSchemaTableProps): JSX.Element {
    const { schemaReloadingById } = useValues(sourceManagementLogic)
    const { inProgressRowsBySchema } = useValues(sourceSettingsLogic)
    const { setSelectedSchemas } = useActions(sourceSettingsLogic)
    const { disabledReason: editDisabledReason } = useSourceEditorAccess(source)
    const [initialLoad, setInitialLoad] = useState(true)

    useEffect(() => {
        if (initialLoad && !isLoading) {
            setInitialLoad(false)
        }
    }, [isLoading, initialLoad])

    return (
        <LemonTable
            dataSource={schemas}
            loading={initialLoad}
            disableTableWhileLoading={false}
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            bulkSelection={{
                getKey: (schema) => schema.id,
                isRowSelectable: () => (editDisabledReason ? { disabledReason: editDisabledReason } : true),
                noun: ['schema', 'schemas'],
                barClassName: 'mb-2',
                renderActions: (ctx) => (
                    <SchemaBulkActions schemas={ctx.selectedRecords} clearSelection={ctx.clearSelection} />
                ),
            }}
            columns={[
                {
                    title: 'Schema',
                    key: 'name',
                    sorter: (a, b) => (a.label ?? a.name).localeCompare(b.label ?? b.name),
                    render: function RenderName(_, schema) {
                        const fullName = schema.label ?? schema.name
                        const name = inSchemaGroup ? splitQualifiedTableName(fullName).tableName : fullName
                        return (
                            <LemonTableLink
                                to={urls.dataWarehouseSourceSchema(prefixedSourceId, schema.id)}
                                title={
                                    <div className="flex items-center gap-1">
                                        <span>{name}</span>
                                        {schema.description && (
                                            <Tooltip title={schema.description}>
                                                <IconInfo className="text-muted-alt text-base" />
                                            </Tooltip>
                                        )}
                                    </div>
                                }
                                description={((): JSX.Element | undefined => {
                                    const tableName = schema.table?.hogql_name ?? schema.table?.name
                                    return tableName ? <code>{tableName}</code> : undefined
                                })()}
                            />
                        )
                    },
                },
                {
                    title: 'Status',
                    key: 'status',
                    sorter: (a, b) => (a.status ?? '').localeCompare(b.status ?? ''),
                    render: (_, schema) => {
                        if (!schema.status) {
                            return <span className="text-muted">—</span>
                        }
                        const openSyncsForSchema = (): void => {
                            setSelectedSchemas([schema.name])
                            router.actions.push(
                                combineUrl(urls.dataWarehouseSource(prefixedSourceId, 'syncs'), {
                                    schema: schema.name,
                                }).url
                            )
                        }
                        const tagContent = (
                            <LemonTag
                                type={StatusTagSetting[schema.status] || 'default'}
                                forceClickable
                                onClick={openSyncsForSchema}
                            >
                                {schema.status}
                            </LemonTag>
                        )
                        return schema.latest_error && schema.status === 'Failed' ? (
                            <Tooltip title={schema.latest_error} interactive>
                                {tagContent}
                            </Tooltip>
                        ) : (
                            tagContent
                        )
                    },
                },
                {
                    title: 'Sync method',
                    key: 'sync_type',
                    render: (_, schema) =>
                        schema.sync_type ? (
                            <LemonTag type="primary">{SyncTypeLabelMap[schema.sync_type]}</LemonTag>
                        ) : (
                            <span className="text-muted">Not set up</span>
                        ),
                },
                {
                    title: 'Frequency',
                    key: 'sync_frequency',
                    sorter: (a, b) => frequencyRank(a.sync_frequency) - frequencyRank(b.sync_frequency),
                    render: (_, schema) => (schema.sync_frequency ? SyncFrequencyLabelMap[schema.sync_frequency] : '—'),
                },
                {
                    title: 'Last synced',
                    key: 'last_synced_at',
                    sorter: (a, b) =>
                        (a.last_synced_at ? dayjs(a.last_synced_at).valueOf() : 0) -
                        (b.last_synced_at ? dayjs(b.last_synced_at).valueOf() : 0),
                    render: (_, schema) =>
                        schema.last_synced_at ? (
                            <TZLabel time={schema.last_synced_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                        ) : (
                            <span className="text-muted">Never</span>
                        ),
                },
                {
                    title: 'Rows synced',
                    key: 'rows_synced',
                    align: 'right',
                    sorter: (a, b) => (a.table?.row_count ?? 0) - (b.table?.row_count ?? 0),
                    render: (_, schema) => {
                        if (schema.table) {
                            return schema.table.row_count?.toLocaleString() ?? 0
                        }
                        // No table yet during the first sync — fall back to the running job's live count.
                        if (schema.status === ExternalDataSchemaStatus.Running) {
                            const rows = inProgressRowsBySchema[schema.id] ?? 0
                            return (
                                <span className="flex items-center justify-end gap-1">
                                    <Spinner textColored className="text-sm" />
                                    {rows.toLocaleString()}
                                </span>
                            )
                        }
                        if (schema.status === ExternalDataSchemaStatus.Completed) {
                            return 0
                        }
                        return <span className="text-muted">—</span>
                    },
                },
                ...(showMetrics
                    ? [
                          {
                              title: 'Rows synced (7d)',
                              key: 'rows_synced_sparkline',
                              render: function RenderSparkline(_: unknown, schema: ExternalDataSourceSchema) {
                                  const lastSyncedAt = schema.last_synced_at ? dayjs(schema.last_synced_at) : null
                                  const syncedWithin7Days =
                                      lastSyncedAt?.isSameOrAfter(dayjs().subtract(7, 'day')) ?? false

                                  if (!syncedWithin7Days) {
                                      return <span className="text-muted">—</span>
                                  }

                                  return (
                                      <AppMetricsSparkline
                                          logicKey={`dwh-schema-sparkline-${schema.id}`}
                                          loadOnChanges
                                          successMetricNames={['rows_synced']}
                                          metricLabels={{ rows_synced: 'Rows synced' }}
                                          forceParams={{
                                              appSource: DATA_WAREHOUSE_APP_SOURCE,
                                              appSourceId: sourceId,
                                              instanceId: schema.id,
                                              metricName: ['rows_synced'],
                                              breakdownBy: 'metric_name',
                                              interval: 'day',
                                              dateFrom: '-7d',
                                          }}
                                      />
                                  )
                              },
                          },
                      ]
                    : []),
                {
                    title: 'Enabled',
                    key: 'should_sync',
                    sorter: (a, b) => Number(a.should_sync) - Number(b.should_sync),
                    render: function RenderShouldSync(_, schema) {
                        return (
                            <SourceEditorAction source={source}>
                                <LemonSwitch
                                    checked={schema.should_sync}
                                    onChange={(active) => {
                                        if (active && !schema.sync_type) {
                                            // No sync method saved yet — send the user to set one up
                                            // before the schema can be enabled.
                                            router.actions.push(
                                                urls.dataWarehouseSourceSchema(
                                                    prefixedSourceId,
                                                    schema.id,
                                                    'configuration',
                                                    'sync-method'
                                                )
                                            )
                                            return
                                        }
                                        if (!active && schema.sync_type === 'cdc') {
                                            LemonDialog.open({
                                                title: 'Disable CDC table?',
                                                content: (
                                                    <div className="text-sm text-secondary space-y-2">
                                                        <p>
                                                            Disabling{' '}
                                                            <strong>{schema.table?.name ?? schema.name}</strong> will
                                                            remove it from the replication publication. Changes made
                                                            while disabled will be permanently lost.
                                                        </p>
                                                        <p>
                                                            Re-enabling this table will require a{' '}
                                                            <strong>full resync</strong> to ensure data consistency.
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
                        )
                    },
                },
                {
                    key: 'actions',
                    width: 0,
                    render: function RenderActions(_, schema) {
                        if (schemaReloadingById[schema.id]) {
                            return (
                                <div className="flex justify-end">
                                    <Spinner />
                                </div>
                            )
                        }
                        return (
                            <div className="flex justify-end items-center gap-1">
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    to={urls.dataWarehouseSourceSchema(prefixedSourceId, schema.id, 'configuration')}
                                >
                                    Configure
                                </LemonButton>
                                <SchemaRowMore
                                    source={source}
                                    schema={schema}
                                    reloadSchema={reloadSchema}
                                    resyncSchema={resyncSchema}
                                    cancelSchema={cancelSchema}
                                    deleteTable={deleteTable}
                                />
                            </div>
                        )
                    },
                },
            ]}
        />
    )
}

function SchemaBulkActions({
    schemas,
    clearSelection,
}: {
    schemas: readonly ExternalDataSourceSchema[]
    clearSelection: () => void
}): JSX.Element {
    const { bulkDisable, bulkSetFrequency, bulkSyncNow, bulkResync, bulkDeleteData } = useActions(sourceSettingsLogic)

    // Wrap every action so the selection clears once it's been kicked off.
    const run = (action: () => void): void => {
        action()
        clearSelection()
    }

    const selected = [...schemas]
    const count = selected.length

    // Only offer frequencies every selected schema supports. Non-CDC schemas floor at 5min, so a
    // mixed selection falls back to the non-CDC set (which CDC also supports).
    const allCdc = selected.length > 0 && selected.every((schema) => schema.sync_type === 'cdc')
    const frequencyOptions = allowedSyncFrequencies(allCdc ? 'cdc' : 'incremental')

    const onDisable = (): void => {
        const hasDataLossType = selected.some((schema) => schema.sync_type === 'cdc' || schema.sync_type === 'webhook')
        if (!hasDataLossType) {
            run(() => bulkDisable(selected))
            return
        }
        LemonDialog.open({
            title: `Disable ${pluralize(count, 'schema', 'schemas')}?`,
            description:
                'Some selected tables use CDC or webhook sync. Disabling stops consuming changes — re-enabling them later requires a full resync to avoid missing data.',
            primaryButton: {
                children: 'Disable',
                status: 'danger',
                onClick: () => run(() => bulkDisable(selected)),
            },
            secondaryButton: { children: 'Cancel', type: 'tertiary' },
        })
    }

    return (
        <>
            <LemonButton type="secondary" size="small" onClick={onDisable}>
                Disable
            </LemonButton>
            <LemonMenu
                items={frequencyOptions.map((interval) => ({
                    label: SyncFrequencyLabelMap[interval],
                    onClick: () => run(() => bulkSetFrequency(selected, interval)),
                }))}
            >
                <LemonButton type="secondary" size="small">
                    Set frequency
                </LemonButton>
            </LemonMenu>
            <LemonButton type="secondary" size="small" onClick={() => run(() => bulkSyncNow(selected))}>
                Sync now
            </LemonButton>
            <More
                size="small"
                overlay={
                    <>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            fullWidth
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete tables and resync ${pluralize(count, 'schema', 'schemas')}?`,
                                    description:
                                        'Existing data for the selected tables is deleted and re-imported from scratch. Only recommended if there is a data-quality issue with previously imported data.',
                                    primaryButton: {
                                        children: 'Delete and resync',
                                        status: 'danger',
                                        onClick: () => run(() => bulkResync(selected)),
                                    },
                                    secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                })
                            }
                        >
                            Delete tables and resync
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            fullWidth
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete ${pluralize(count, 'table', 'tables')} from PostHog?`,
                                    description:
                                        'Removes the synced tables from PostHog. The data in the source is not touched.',
                                    primaryButton: {
                                        children: 'Delete from PostHog',
                                        status: 'danger',
                                        onClick: () => run(() => bulkDeleteData(selected)),
                                    },
                                    secondaryButton: { children: 'Cancel', type: 'tertiary' },
                                })
                            }
                        >
                            Delete tables from PostHog
                        </LemonButton>
                    </>
                }
            />
        </>
    )
}

function SchemaRowMore({
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
        <SourceEditorAction source={source}>
            {({ disabledReason }) => (
                <More
                    disabledReason={disabledReason}
                    overlay={
                        <>
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
                                    type="tertiary"
                                    size="xsmall"
                                    fullWidth
                                    onClick={() => reloadSchema(schema)}
                                    disabledReason={!schema.sync_type ? 'Set up the sync method first' : undefined}
                                >
                                    {schema.sync_type === 'cdc' ? 'Sync CDC now' : 'Sync now'}
                                </LemonButton>
                            </Tooltip>
                            {schema.status === 'Running' && (
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    fullWidth
                                    status="danger"
                                    onClick={() => cancelSchema(schema)}
                                >
                                    Cancel sync
                                </LemonButton>
                            )}
                            {schema.sync_type === 'cdc' && (
                                <Tooltip title="Re-snapshot the full table and replay all CDC changes on top. Use this to recover from a corrupted or out-of-sync table.">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        fullWidth
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
                                    >
                                        Full resync
                                    </LemonButton>
                                </Tooltip>
                            )}
                            {(schema.incremental || schema.sync_type === 'webhook') && (
                                <Tooltip title="Completely resync data by deleting the existing table and re-importing. Only recommended if there is an issue with data quality in previously imported data.">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        fullWidth
                                        status="danger"
                                        onClick={() => resyncSchema(schema)}
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
                                        type="tertiary"
                                        size="xsmall"
                                        fullWidth
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
                                    >
                                        Delete table from PostHog
                                    </LemonButton>
                                </Tooltip>
                            )}
                        </>
                    }
                />
            )}
        </SourceEditorAction>
    )
}
