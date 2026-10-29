import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall, IconStar, IconStarFilled } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonTable, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

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
import { isFileUploadSource, sourceTypeLabel } from '../fileUploadSources'
import { managedSourcesTableLogic, syncingSchemasByStatus, totalRowsSynced } from '../logics/managedSourcesTableLogic'
import { sourceManagementLogic } from '../logics/sourceManagementLogic'
import { FreeHistoricalSyncsBanner } from './FreeHistoricalSyncsBanner'
import { DATA_WAREHOUSE_APP_SOURCE } from './metrics/DataWarehouseMetrics'
// eslint-disable-next-line import/no-cycle
import { SourceIcon } from './SourceIcon'

export function ManagedSourcesTable(): JSX.Element {
    const { dataWarehouseSourcesLoading, sourceReloadingById, managedSearchTerm } = useValues(sourceManagementLogic)
    const { deleteSource, reloadSource, setManagedSearchTerm } = useActions(sourceManagementLogic)
    const { sortedManagedSources, managedSourcesSorting, starredSourceShortcuts, shortcutDataLoading } =
        useValues(managedSourcesTableLogic)
    const { setManagedSourcesSorting, toggleSourceStarred } = useActions(managedSourcesTableLogic)
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showMetrics = !!featureFlags[FEATURE_FLAGS.DWH_SOURCE_METRICS]

    return (
        <div>
            <div className="flex gap-2 justify-between items-center mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    onChange={setManagedSearchTerm}
                    value={managedSearchTerm}
                    data-attr="managed-sources-search"
                />
            </div>
            <LemonTable
                id="managed-sources"
                // Labels and icons come from `availableSources`, so rows shown before it answers
                // would render raw source types and then swap under the reader.
                dataSource={availableSourcesLoading ? [] : sortedManagedSources}
                loading={dataWarehouseSourcesLoading || availableSourcesLoading}
                disableTableWhileLoading={false}
                pagination={{ pageSize: 10 }}
                scrollToTopOnPageChange={false}
                // The logic sorts, because LemonTable reverses a column sorter and would sink starred sources.
                sorting={managedSourcesSorting}
                onSort={setManagedSourcesSorting}
                useURLForSorting={false}
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
                        className: '!pl-2',
                        render: (_, source) => {
                            const starred = !!starredSourceShortcuts[source.id]
                            return (
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        size="xsmall"
                                        noPadding
                                        icon={starred ? <IconStarFilled /> : <IconStar />}
                                        tooltip={starred ? 'Remove from starred' : 'Add to starred'}
                                        onClick={() => toggleSourceStarred(source)}
                                        disabledReason={shortcutDataLoading ? 'Updating starred items' : undefined}
                                        data-attr="managed-sources-star"
                                    />
                                    <SourceIcon type={source.source_type} engine={source.engine} />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Source',
                        key: 'name',
                        sorter: true,
                        render: (_, source) => (
                            <LemonTableLink
                                to={urls.dataWarehouseSource(`managed-${source.id}`)}
                                title={sourceTypeLabel(source.source_type, availableSources)}
                                description={source.description}
                            />
                        ),
                    },
                    {
                        title: 'Table prefix',
                        key: 'prefix',
                        sorter: true,
                        render: (_, source) => source.prefix || '-',
                    },
                    {
                        title: 'Last Successful Run',
                        key: 'last_run_at',
                        tooltip: 'Time of the last run that completed a data import',
                        sorter: true,
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
                        sorter: true,
                        render: (_, source) => totalRowsSynced(source).toLocaleString(),
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
                        sorter: true,
                        render: (_, source) => {
                            if (!source.status) {
                                return null
                            }
                            const counts = syncingSchemasByStatus(source)

                            if (counts.length === 0) {
                                // Source has schemas but none are enabled — source.status can be stale
                                // ("Running" from before they were disabled), so show a neutral tag instead.
                                if (source.schemas.length > 0) {
                                    return <LemonTag type="muted">Not syncing</LemonTag>
                                }
                                const tagContent = (
                                    <LemonTag type={StatusTagSetting[source.status] || 'default'}>
                                        {source.status}
                                    </LemonTag>
                                )
                                return source.latest_error && source.status === 'Failed' ? (
                                    <Tooltip title={source.latest_error} interactive>
                                        {tagContent}
                                    </Tooltip>
                                ) : (
                                    tagContent
                                )
                            }

                            const sourceUrl = urls.dataWarehouseSource(`managed-${source.id}`)
                            return (
                                <div className="flex flex-wrap gap-1">
                                    {counts.map(({ status, schemas }) => (
                                        <Tooltip
                                            key={status}
                                            interactive
                                            title={
                                                <ul className="list-disc pl-4 m-0">
                                                    {schemas.map((s) => (
                                                        <li key={s.id}>{s.label ?? s.name}</li>
                                                    ))}
                                                </ul>
                                            }
                                        >
                                            <LemonTag
                                                type={StatusTagSetting[status] || 'default'}
                                                forceClickable
                                                onClick={() => router.actions.push(sourceUrl)}
                                            >
                                                {schemas.length} {status.toLowerCase()}
                                            </LemonTag>
                                        </Tooltip>
                                    ))}
                                </div>
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
                                                    {!isFileUploadSource(source) && (
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
                                                    )}

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
