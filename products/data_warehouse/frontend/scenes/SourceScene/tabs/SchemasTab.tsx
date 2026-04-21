import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ExternalDataSourceType, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { DATA_WAREHOUSE_APP_SOURCE } from 'products/data_warehouse/frontend/shared/components/metrics/DataWarehouseMetrics'
import { SourceEditorAction } from 'products/data_warehouse/frontend/shared/components/SourceEditorAction'
import { StatusTagSetting, SyncTypeLabelMap } from 'products/data_warehouse/frontend/utils'

import { DirectQuerySchemasTab } from './DirectQuerySchemasTab'
import { sourceSettingsLogic } from './sourceSettingsLogic'

const REVENUE_ENABLED_SOURCES: ExternalDataSourceType[] = ['Stripe']

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
    const { featureFlags } = useValues(featureFlagLogic)

    const isDirectQuerySource =
        !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY] && source?.access_method === 'direct'

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
        showEnabledSchemasOnly,
        schemaNameFilter,
        syncingNow,
        refreshingSchemas,
    } = useValues(sourceSettingsLogic)
    const { setShowEnabledSchemasOnly, setSchemaNameFilter, syncNow, refreshSchemas, updateSchema } =
        useActions(sourceSettingsLogic)
    const { addProductIntentForCrossSell } = useActions(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showMetrics = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]
    // `id` is the cleaned source id; URLs use the `managed-` prefix
    const prefixedSourceId = `managed-${id}`

    return (
        <>
            <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-3">
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
                    <span className="text-muted text-sm">{pluralize(filteredSchemas.length, 'schema', 'schemas')}</span>
                </div>
                <div className="flex items-center gap-2">
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
                            Sync now
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
            <ManagedSchemaTable
                schemas={filteredSchemas}
                isLoading={sourceLoading}
                source={source}
                sourceId={id}
                prefixedSourceId={prefixedSourceId}
                updateSchema={updateSchema}
                showMetrics={showMetrics}
            />
            {source?.source_type &&
                REVENUE_ENABLED_SOURCES.includes(source.source_type) &&
                featureFlags[FEATURE_FLAGS.REVENUE_ANALYTICS] && (
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            className="mt-2"
                            tooltip="This source is feeding data into our Revenue analytics product - currently in beta."
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
                            <LemonTag className="ml-2" type="warning" size="small">
                                BETA
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
    showMetrics: boolean
}

function ManagedSchemaTable({
    schemas,
    isLoading,
    source,
    sourceId,
    prefixedSourceId,
    updateSchema,
    showMetrics,
}: ManagedSchemaTableProps): JSX.Element {
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
            columns={[
                {
                    title: 'Schema',
                    key: 'name',
                    render: function RenderName(_, schema) {
                        const name = schema.label ?? schema.name
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
                                description={schema.table?.name ? <code>{schema.table.name}</code> : undefined}
                            />
                        )
                    },
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, schema) => {
                        if (!schema.status) {
                            return <span className="text-muted">—</span>
                        }
                        const tagContent = (
                            <LemonTag type={StatusTagSetting[schema.status] || 'default'}>{schema.status}</LemonTag>
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
                    render: (_, schema) => schema.sync_frequency || '—',
                },
                {
                    title: 'Last synced',
                    key: 'last_synced_at',
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
                    render: (_, schema) => {
                        if (schema.table) {
                            return schema.table.row_count?.toLocaleString() ?? 0
                        }
                        if (schema.status === 'Completed') {
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
                                  return (
                                      <AppMetricsSparkline
                                          logicKey={`dwh-schema-sparkline-${schema.id}`}
                                          loadOnChanges
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
                                    disabledReason={
                                        schema.sync_type === null ? 'Set up the sync method first' : undefined
                                    }
                                    checked={schema.should_sync}
                                    onChange={(active) => {
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
                    key: 'link',
                    width: 0,
                    render: function RenderLink(_, schema) {
                        return (
                            <Link to={urls.dataWarehouseSourceSchema(prefixedSourceId, schema.id, 'configuration')}>
                                Configure
                            </Link>
                        )
                    },
                },
            ]}
        />
    )
}
