import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { StatusTagSetting } from 'products/data_warehouse/frontend/utils'

import { availableSourcesLogic } from '../../scenes/NewSourceScene/availableSourcesLogic'
import { sourceManagementLogic } from '../logics/sourceManagementLogic'
import { FreeHistoricalSyncsBanner } from './FreeHistoricalSyncsBanner'
import { DATA_WAREHOUSE_APP_SOURCE } from './metrics/DataWarehouseMetrics'
// eslint-disable-next-line import/no-cycle
import { SourceIcon } from './SourceIcon'

export function ManagedSourcesTable(): JSX.Element {
    const { filteredManagedSources, dataWarehouseSourcesLoading, sourceReloadingById, managedSearchTerm } =
        useValues(sourceManagementLogic)
    const { deleteSource, reloadSource, setManagedSearchTerm } = useActions(sourceManagementLogic)
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showMetrics = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]

    if (availableSourcesLoading) {
        return <LemonSkeleton />
    }

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    onChange={setManagedSearchTerm}
                    value={managedSearchTerm}
                />
            </div>
            <LemonTable
                id="managed-sources"
                dataSource={filteredManagedSources}
                loading={dataWarehouseSourcesLoading}
                disableTableWhileLoading={false}
                pagination={{ pageSize: 10 }}
                emptyState={
                    <div className="flex flex-col items-center gap-2 py-2">
                        <span>{managedSearchTerm ? 'No sources matching your search' : 'No managed sources'}</span>
                        <LemonButton
                            type="secondary"
                            icon={<IconPlusSmall />}
                            to={urls.dataWarehouseSourceNew()}
                            size="small"
                            data-attr="managed-sources-empty-new-source"
                        >
                            New source
                        </LemonButton>
                    </div>
                }
                columns={[
                    {
                        width: 0,
                        render: (_, source) => <SourceIcon type={source.source_type} engine={source.engine} />,
                    },
                    {
                        title: 'Source',
                        key: 'name',
                        render: (_, source) => (
                            <LemonTableLink
                                to={urls.dataWarehouseSource(`managed-${source.id}`)}
                                title={availableSources?.[source.source_type]?.label ?? source.source_type}
                                description={source.description}
                            />
                        ),
                    },
                    {
                        title: 'Table prefix',
                        key: 'prefix',
                        render: (_, source) => source.prefix || '-',
                    },
                    {
                        title: 'Last Successful Run',
                        key: 'last_run_at',
                        tooltip: 'Time of the last run that completed a data import',
                        render: (_, run) => {
                            return run.last_run_at ? (
                                <TZLabel time={run.last_run_at} formatDate="MMM DD, YYYY" formatTime="HH:mm" />
                            ) : (
                                'Never'
                            )
                        },
                    },
                    {
                        title: 'Total Rows Synced',
                        key: 'rows_synced',
                        tooltip: 'Total number of rows synced across all schemas in this source',
                        render: (_, source) =>
                            source.schemas
                                .reduce((acc, schema) => acc + (schema.table?.row_count ?? 0), 0)
                                .toLocaleString(),
                    },
                    ...(showMetrics
                        ? [
                              {
                                  title: 'Rows synced (7d)',
                                  key: 'rows_synced_sparkline',
                                  render: function RenderSparkline(_: unknown, source: { id: string }) {
                                      return (
                                          <AppMetricsSparkline
                                              logicKey={`dwh-source-sparkline-${source.id}`}
                                              loadOnChanges
                                              successMetricNames={['rows_synced']}
                                              metricLabels={{ rows_synced: 'Rows synced' }}
                                              forceParams={{
                                                  appSource: DATA_WAREHOUSE_APP_SOURCE,
                                                  appSourceId: source.id,
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
                        title: 'Status',
                        key: 'status',
                        render: (_, source) => {
                            if (!source.status) {
                                return null
                            }
                            const tagContent = (
                                <LemonTag type={StatusTagSetting[source.status] || 'default'}>{source.status}</LemonTag>
                            )
                            return source.latest_error && source.status === 'Failed' ? (
                                <Tooltip title={source.latest_error} interactive>
                                    {tagContent}
                                </Tooltip>
                            ) : (
                                tagContent
                            )
                        },
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, source) => (
                            <div className="flex flex-row justify-end">
                                {sourceReloadingById[source.id] ? (
                                    <div>
                                        <Spinner />
                                    </div>
                                ) : (
                                    <div>
                                        <More
                                            overlay={
                                                <>
                                                    <AccessControlAction
                                                        resourceType={AccessControlResourceType.ExternalDataSource}
                                                        minAccessLevel={AccessControlLevel.Editor}
                                                        userAccessLevel={source.user_access_level}
                                                    >
                                                        {({ disabledReason }) => (
                                                            <Tooltip title="Start the data import for this schema again">
                                                                <LemonButton
                                                                    type="tertiary"
                                                                    data-attr={`reload-data-warehouse-${source.source_type}`}
                                                                    key={`reload-data-warehouse-${source.source_type}`}
                                                                    onClick={() => {
                                                                        reloadSource(source)
                                                                    }}
                                                                    disabledReason={disabledReason}
                                                                >
                                                                    Reload
                                                                </LemonButton>
                                                            </Tooltip>
                                                        )}
                                                    </AccessControlAction>

                                                    <AccessControlAction
                                                        resourceType={AccessControlResourceType.ExternalDataSource}
                                                        minAccessLevel={AccessControlLevel.Editor}
                                                        userAccessLevel={source.user_access_level}
                                                    >
                                                        {({ disabledReason }) => (
                                                            <LemonButton
                                                                status="danger"
                                                                data-attr={`delete-data-warehouse-${source.source_type}`}
                                                                key={`delete-data-warehouse-${source.source_type}`}
                                                                onClick={() => {
                                                                    LemonDialog.open({
                                                                        title: 'Delete data source?',
                                                                        description:
                                                                            'Are you sure you want to delete this data source? All related tables will be deleted.',

                                                                        primaryButton: {
                                                                            children: 'Delete',
                                                                            status: 'danger',
                                                                            onClick: () => deleteSource(source),
                                                                        },
                                                                        secondaryButton: {
                                                                            children: 'Cancel',
                                                                        },
                                                                    })
                                                                }}
                                                                disabledReason={disabledReason}
                                                            >
                                                                Delete
                                                            </LemonButton>
                                                        )}
                                                    </AccessControlAction>
                                                </>
                                            }
                                        />
                                    </div>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
            <FreeHistoricalSyncsBanner />
        </div>
    )
}

const DOCS_BASE_URL = 'https://posthog.com/docs/cdp/sources/'

export function getDataWarehouseSourceUrl(service: string): string {
    switch (service) {
        case 'aws':
            return `${DOCS_BASE_URL}s3`
        case 'google-cloud':
            return `${DOCS_BASE_URL}gcs`
        case 'azure':
            return `${DOCS_BASE_URL}azure-blob`
        case 'cloudflare-r2':
            return `${DOCS_BASE_URL}r2`
        default:
            return `${DOCS_BASE_URL}${service.toLowerCase()}`
    }
}
