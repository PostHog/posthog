import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconInfo, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { IconCancel, IconExclamation, IconRadioButtonUnchecked, IconSync } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DataWarehouseActivityRecord, DataWarehouseDashboardDataSource, PipelineTab } from '~/types'

import { DataWarehouseRowsSyncedGraph } from './DataWarehouseRowsSyncedGraph'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

export const scene: SceneExport = { component: DataWarehouseScene }

const LIST_SIZE = 5

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { materializedViews, activityPaginationState, computedAllSources, totalRowsStats, actionableIssues } =
        useValues(dataWarehouseSceneLogic)
    const { setActivityCurrentPage } = useActions(dataWarehouseSceneLogic)

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

    const StatusIcon = ({ status }: { status?: string }): JSX.Element => {
        const s = (status || '').toLowerCase()

        if (s === 'failed' || s === 'error') {
            return <IconCancel className="text-danger" />
        }
        if (s === 'warning' || s.includes('billing')) {
            return <IconExclamation className="text-warning" />
        }
        if (s === 'running') {
            return <IconSync className="animate-spin" />
        }
        if (s === 'completed' || s === 'success') {
            return <IconCheckCircle className="text-success" />
        }
        return <IconRadioButtonUnchecked className="text-muted" />
    }

    const StatusTag = ({ status }: { status?: string }): JSX.Element => {
        const s = (status || '').toLowerCase()

        const type = ['failed', 'error'].includes(s)
            ? ('danger' as const)
            : s === 'warning'
              ? ('warning' as const)
              : ['completed', 'success'].includes(s)
                ? ('success' as const)
                : s === 'running'
                  ? ('none' as const)
                  : ('muted' as const)

        const size = (['completed', 'failed', 'error'].includes(s) ? 'medium' : 'small') as 'medium' | 'small'

        return (
            <LemonTag
                size={size}
                type={type}
                className="px-1 rounded-lg"
                style={type === 'none' ? { color: '#3b82f6', borderColor: '#3b82f6' } : undefined}
            >
                {s || '—'}
            </LemonTag>
        )
    }

    const materializedCount = materializedViews?.length || 0
    const runningCount = materializedViews?.filter((v) => v.status?.toLowerCase() === 'running').length || 0

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        return <NotFound object="Data Warehouse" />
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div className="flex flex-col">
                    <h1 className="text-2xl font-semibold">Data Warehouse</h1>
                    <p className="text-muted">Manage your data warehouse sources and queries</p>
                </div>
                <div className="flex gap-2">
                    <LemonButton type="primary" to={urls.dataWarehouseSourceNew()} icon={<IconPlusSmall />}>
                        New source
                    </LemonButton>
                    <LemonButton type="secondary" to={urls.sqlEditor()}>
                        Create view
                    </LemonButton>
                </div>
            </div>

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

            <DataWarehouseRowsSyncedGraph />

            {actionableIssues && actionableIssues.length > 0 && (
                <div className="bg-transparent">
                    <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-semibold text-xl">Actionable Issues ({actionableIssues.length})</h3>
                    </div>
                    <div className="space-y-3">
                        {actionableIssues.map((issue) => {
                            const isCritical = issue.severity === 'critical'
                            const bgClass = isCritical ? 'bg-red-50 border-red-200' : 'bg-yellow-50 border-yellow-200'

                            return (
                                <div key={issue.id} className={`border rounded-xl px-4 py-2 ${bgClass} shadow-sm`}>
                                    <div className="flex items-start gap-3">
                                        <div className="flex-shrink-0 pt-0.5">
                                            {isCritical ? (
                                                <IconCancel className="text-red-600 w-5 h-5" />
                                            ) : (
                                                <IconExclamation className="text-yellow-600 w-5 h-5" />
                                            )}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-2">
                                                <span className="font-semibold text-gray-900">{issue.title}</span>
                                                <LemonTag
                                                    type={isCritical ? 'danger' : 'warning'}
                                                    size="small"
                                                    className="px-2 py-0.5 font-medium uppercase"
                                                >
                                                    {issue.severity}
                                                </LemonTag>
                                                <span className="text-xs text-gray-500">
                                                    <TZLabel
                                                        time={issue.timestamp}
                                                        formatDate="MMM DD"
                                                        formatTime="HH:mm"
                                                    />
                                                </span>
                                            </div>
                                            <div className="text-sm text-gray-700">
                                                {issue.description}
                                                {issue.count && issue.count > 1 && (
                                                    <span className="ml-1 text-gray-500 font-medium">
                                                        ({issue.count} recent failures)
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                        <div className="ml-4 flex-shrink-0">
                                            <LemonButton
                                                type={isCritical ? 'primary' : 'secondary'}
                                                size="small"
                                                to={issue.actionUrl}
                                                className="font-medium"
                                            >
                                                {issue.actionType
                                                    .replace(/_/g, ' ')
                                                    .replace(/\b\w/g, (l) => l.toUpperCase())}
                                            </LemonButton>
                                        </div>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <div className="lg:col-span-2 space-y-2">
                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                                <h3 className="font-semibold text-xl">Data Sources</h3>
                                <LemonTag size="medium" type="muted" className="mb-2 p-1 px-2 rounded-xl">
                                    {computedAllSources.length} connected
                                </LemonTag>
                            </div>
                            <LemonButton
                                to={urls.pipeline(PipelineTab.Sources)}
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
                        />
                        <PaginationControl {...viewsPagination} nouns={['view', 'views']} />
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-xl">Recent Activity</h3>
                        </div>
                        <LemonTable
                            dataSource={activityPagination.dataSourcePage as DataWarehouseActivityRecord[]}
                            columns={activityColumns}
                            rowKey={(r) => `${r.type}-${r.name}-${r.created_at}`}
                        />
                        <PaginationControl {...activityPagination} nouns={['activity', 'activities']} />
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}
