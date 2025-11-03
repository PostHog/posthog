import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonCard, LemonSegmentedButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PaginationControl } from 'lib/lemon-ui/PaginationControl'

import { DataWarehouseActivityRecord } from '~/types'

import { dataWarehouseSceneLogic } from '../dataWarehouseSceneLogic'
import { JobStatsChart } from './components/JobStatsChart'
import { StatusIcon, StatusTag } from './components/StatusComponents'

const LIST_SIZE = 8

export function OverviewTab(): JSX.Element {
    const { activityPaginationState, totalRowsStats, totalRowsStatsLoading, tablesLoading, jobStats, jobStatsLoading } =
        useValues(dataWarehouseSceneLogic)
    const { setActivityCurrentPage, loadJobStats } = useActions(dataWarehouseSceneLogic)

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

    return (
        <>
            <div className="grid grid-cols-1 lg:grid-cols-6 gap-4">
                <LemonCard className="p-4 hover:transform-none">
                    <div className="space-y-6">
                        <div>
                            <div className="flex items-start gap-1">
                                <div className="text-sm text-muted">Rows Processed</div>
                                <Tooltip
                                    title="Total rows processed this month by all data sources and materialized views"
                                    placement="bottom"
                                >
                                    <IconInfo className="text-muted mt-0.5" />
                                </Tooltip>
                            </div>
                            <div className="text-2xl font-semibold mt-1 flex items-center gap-2">
                                {totalRowsStatsLoading && !totalRowsStats?.total_rows ? (
                                    <Spinner className="text-muted" />
                                ) : (
                                    (totalRowsStats?.total_rows ?? 0).toLocaleString()
                                )}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-muted">Currently running source syncs</div>
                            <div className="text-2xl font-semibold mt-1 flex items-center gap-2">
                                {jobStatsLoading && !jobStats ? (
                                    <Spinner className="text-muted" />
                                ) : (
                                    (jobStats?.external_data_jobs.running ?? 0)
                                )}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-muted">Currently running materialized views</div>
                            <div className="text-2xl font-semibold mt-1 flex items-center gap-2">
                                {jobStatsLoading && !jobStats ? (
                                    <Spinner className="text-muted" />
                                ) : (
                                    (jobStats?.modeling_jobs.running ?? 0)
                                )}
                            </div>
                        </div>
                    </div>
                </LemonCard>

                <LemonCard className="p-4 hover:transform-none lg:col-span-5">
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
                            size="xsmall"
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
                                    <div className="text-xl font-semibold">{jobStats.total_jobs.toLocaleString()}</div>
                                </div>
                                <div>
                                    <div className="text-xs text-muted">Successful</div>
                                    <div className="text-xl font-semibold text-success flex items-center gap-1">
                                        {jobStats.successful_jobs.toLocaleString()}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-xs text-muted">Failed</div>
                                    <div className="text-xl font-semibold text-danger flex items-center gap-1">
                                        {jobStats.failed_jobs.toLocaleString()}
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
            </div>

            <LemonCard className="hover:transform-none mt-4">
                <div className="flex items-center gap-2 pb-2">
                    <span className="font-semibold text-xl">Recent Activity</span>
                    {tablesLoading && activityPagination.dataSourcePage.length !== 0 && (
                        <Spinner className="text-muted" />
                    )}
                </div>
                <LemonTable
                    dataSource={activityPagination.dataSourcePage as DataWarehouseActivityRecord[]}
                    columns={activityColumns}
                    rowKey={(r) => `${r.type}-${r.name}-${r.created_at}`}
                    loading={tablesLoading && activityPagination.dataSourcePage.length === 0}
                    loadingSkeletonRows={3}
                />
                <div className="px-4 pb-4">
                    <PaginationControl {...activityPagination} nouns={['activity', 'activities']} />
                </div>
            </LemonCard>
        </>
    )
}
