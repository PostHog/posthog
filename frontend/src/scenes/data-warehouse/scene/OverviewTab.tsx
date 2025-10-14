import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSegmentedButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import { DataWarehouseActivityRecord, DataWarehouseDashboardDataSource } from '~/types'

import { dataWarehouseSceneLogic } from '../dataWarehouseSceneLogic'
import { JobStatsChart } from './components/JobStatsChart'
import { StatusIcon, StatusTag } from './components/StatusComponents'

const LIST_SIZE = 5

export function OverviewTab(): JSX.Element {
    const {
        materializedViews,
        activityPaginationState,
        computedAllSources,
        totalRowsStats,
        tablesLoading,
        jobStats,
        jobStatsLoading,
    } = useValues(dataWarehouseSceneLogic)
    const { setActivityCurrentPage, loadJobStats } = useActions(dataWarehouseSceneLogic)

    const sourcesPagination = usePagination(computedAllSources, { pageSize: LIST_SIZE }, 'sources')
    const viewsPagination = usePagination(materializedViews || [], { pageSize: LIST_SIZE }, 'views')

    const activityPagination = {
        currentPage: activityPaginationState.currentPage,
        pageCount: activityPaginationState.pageCount,
        dataSourcePage: activityPaginationState.dataSourcePage,
        currentStartIndex: activityPaginationState.currentStartIndex,
        currentEndIndex: activityPaginationState.currentEndIndex,
        entryCount: activityPaginationState.entryCount,
        setCurrentPage: setActivityCurrentPage,
        pagination: { pageSize: LIST_SIZE },
    }

    const sourceColumns: LemonTableColumns<DataWarehouseDashboardDataSource> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, source) => (
                <div className="flex items-center gap-1">
                    <StatusIcon status={source.status ?? undefined} />
                    {source.url ? <LemonTableLink to={source.url} title={source.name} /> : <span>{source.name}</span>}
                </div>
            ),
        },
        {
            title: 'Last sync',
            key: 'lastSync',
            tooltip: 'Time of the last successful data synchronization',
            render: (_, source) => (source.lastSync ? <TZLabel time={source.lastSync} /> : '—'),
        },
        {
            title: 'Rows',
            key: 'rowCount',
            align: 'right',
            tooltip: 'Total number of rows in this data source',
            render: (_, source) => (source.rowCount !== null ? source.rowCount.toLocaleString() : '0'),
        },
        {
            title: 'Status',
            key: 'status',
            align: 'right',
            render: (_, source) => (source.status ? <StatusTag status={source.status} /> : '—'),
        },
    ]

    const viewColumns: LemonTableColumns<any> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, view) => (
                <div className="flex items-center gap-1">
                    <StatusIcon status={view.status} />
                    <LemonTableLink to={urls.sqlEditor(undefined, view.id)} title={view.name} />
                </div>
            ),
        },
        {
            title: 'Last run',
            key: 'last_run_at',
            tooltip: 'Time of the last materialization run',
            render: (_, view) => (view.last_run_at ? <TZLabel time={view.last_run_at} /> : 'Never'),
        },
        {
            title: 'Rows',
            key: 'row_count',
            align: 'right',
            tooltip: 'Number of rows in the materialized view',
            render: (_, view) =>
                view.row_count !== undefined && view.row_count !== null ? view.row_count.toLocaleString() : '0',
        },
        {
            title: 'Status',
            key: 'status',
            align: 'right',
            render: (_, view) => <StatusTag status={view.status} />,
        },
    ]

    const activityColumns: LemonTableColumns<DataWarehouseActivityRecord> = [
        {
            title: 'Activity',
            key: 'name',
            render: (_, activity) => (
                <div className="flex items-center gap-1">
                    <StatusIcon status={activity.status} />
                    <span>{activity.name}</span>
                    <LemonTag size="medium" type="muted" className="px-1 rounded-lg ml-1">
                        {activity.type}
                    </LemonTag>
                </div>
            ),
        },
        {
            title: 'When',
            key: 'created_at',
            tooltip: 'Time when this job was created',
            render: (_, activity) => <TZLabel time={activity.created_at} />,
        },
        {
            title: 'Rows',
            key: 'rows',
            align: 'right',
            tooltip: 'Number of rows processed in this job',
            render: (_, activity) => (activity.rows !== null ? activity.rows.toLocaleString() : '0'),
        },
        {
            title: 'Status',
            key: 'status',
            align: 'right',
            render: (_, activity) => <StatusTag status={activity.status} />,
        },
    ]

    const materializedCount = materializedViews.length
    const runningCount = materializedViews.filter((v: any) => v.status?.toLowerCase() === 'running').length

    return (
        <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <LemonCard className="p-4 hover:transform-none">
                    <div className="flex items-start gap-1">
                        <div className="text-sm text-muted">Rows Processed (in current billing period)</div>
                        <Tooltip
                            title="Total rows processed this month by all data sources and materialized views"
                            placement="bottom"
                        >
                            <IconInfo className="text-muted mt-0.5" />
                        </Tooltip>
                    </div>
                    <div className="text-2xl font-semibold mt-1">
                        {(totalRowsStats?.total_rows ?? 0).toLocaleString()}{' '}
                    </div>
                </LemonCard>
                <LemonCard className="p-4 hover:transform-none">
                    <div className="text-sm text-muted">Materialized Views</div>
                    <div className="text-2xl font-semibold mt-1">{materializedCount}</div>
                    {runningCount > 0 && <div className="text-xs text-muted">{runningCount} running</div>}
                </LemonCard>
            </div>

            <LemonCard className="p-4 hover:transform-none mt-4">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <div className="flex items-start gap-1">
                            <div className="text-sm text-muted">Sync Success Rate</div>
                            <Tooltip title="Success and failure rate of data warehouse syncs" placement="bottom">
                                <IconInfo className="text-muted mt-0.5" />
                            </Tooltip>
                        </div>
                        {jobStatsLoading && <Spinner className="text-muted" />}
                    </div>
                    <LemonSegmentedButton
                        size="small"
                        value={jobStats?.days ?? 7}
                        onChange={(value) => loadJobStats({ days: value as 1 | 7 | 30 })}
                        options={[
                            { value: 1, label: '24h' },
                            { value: 7, label: '7d' },
                            { value: 30, label: '30d' },
                        ]}
                    />
                </div>
                {jobStats && (
                    <div className="space-y-4">
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                            <div>
                                <div className="text-xs text-muted">Total Jobs</div>
                                <div className="text-2xl font-semibold">{jobStats.total_jobs}</div>
                            </div>
                            <div>
                                <div className="text-xs text-muted">Successful</div>
                                <div className="text-2xl font-semibold text-success flex items-center gap-1">
                                    {jobStats.successful_jobs}
                                    {jobStats.total_jobs > 0 && (
                                        <span className="text-base">
                                            ({Math.round((jobStats.successful_jobs / jobStats.total_jobs) * 100)}%)
                                        </span>
                                    )}
                                </div>
                            </div>
                            <div>
                                <div className="text-xs text-muted">Failed</div>
                                <div className="text-2xl font-semibold text-danger flex items-center gap-1">
                                    {jobStats.failed_jobs}
                                    {jobStats.total_jobs > 0 && (
                                        <span className="text-base">
                                            ({Math.round((jobStats.failed_jobs / jobStats.total_jobs) * 100)}%)
                                        </span>
                                    )}
                                </div>
                            </div>
                        </div>
                        {jobStats.total_jobs > 0 && (
                            <div className="pt-2">
                                <JobStatsChart jobStats={jobStats} />
                            </div>
                        )}
                    </div>
                )}
            </LemonCard>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-4">
                <div className="lg:col-span-2 space-y-2">
                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-xl">Recent Activity</h3>
                        </div>
                        <LemonTable
                            dataSource={activityPagination.dataSourcePage as DataWarehouseActivityRecord[]}
                            columns={activityColumns}
                            rowKey={(r) => `${r.type}-${r.name}-${r.created_at}`}
                            loading={tablesLoading}
                            loadingSkeletonRows={3}
                        />
                        <PaginationControl {...activityPagination} nouns={['activity', 'activities']} />
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                                <h3 className="font-semibold text-xl">Data Sources</h3>
                                <LemonTag size="medium" type="muted" className="mb-2 p-1 px-2 rounded-xl">
                                    {computedAllSources.length} connected
                                </LemonTag>
                            </div>
                            <LemonButton
                                to={urls.dataPipelines('sources')}
                                size="small"
                                type="secondary"
                                className="mb-3"
                            >
                                View All
                            </LemonButton>
                        </div>
                        <LemonTable
                            dataSource={sourcesPagination.dataSourcePage as DataWarehouseDashboardDataSource[]}
                            columns={sourceColumns}
                            rowKey="id"
                            loading={tablesLoading}
                            loadingSkeletonRows={3}
                        />
                        <PaginationControl {...sourcesPagination} nouns={['source', 'sources']} />
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center gap-2">
                            <h3 className="font-semibold text-xl">Views</h3>
                            <LemonTag size="medium" type="muted" className="mb-2 p-1 px-2 rounded-xl">
                                {materializedViews?.length || 0} views
                            </LemonTag>
                        </div>
                        <LemonTable
                            dataSource={viewsPagination.dataSourcePage as any[]}
                            columns={viewColumns}
                            rowKey="id"
                            loading={tablesLoading}
                            loadingSkeletonRows={3}
                        />
                        <PaginationControl {...viewsPagination} nouns={['view', 'views']} />
                    </LemonCard>
                </div>
            </div>
        </>
    )
}
