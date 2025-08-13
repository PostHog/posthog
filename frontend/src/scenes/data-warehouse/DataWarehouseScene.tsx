import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PipelineTab } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues, useActions } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { urls } from 'scenes/urls'
import { LemonButton, LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { IconPlusSmall, IconCheckCircle, IconInfo } from '@posthog/icons'
import { dataWarehouseSceneLogic } from './settings/dataWarehouseSceneLogic'
import { dataWarehouseSettingsLogic } from './settings/dataWarehouseSettingsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { IconCancel, IconSync, IconExclamation, IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'
import { externalDataSourcesLogic, DashboardDataSource, type UnifiedRecentActivity } from './externalDataSourcesLogic'

export const scene: SceneExport = { component: DataWarehouseScene }

const LIST_SIZE = 5

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { materializedViews } = useValues(dataWarehouseSceneLogic)
    const { totalRowsProcessed, recentActivity, dataWarehouseSources } = useValues(externalDataSourcesLogic)
    const { computedAllSources } = useValues(dataWarehouseSettingsLogic)
    const { loadTotalRowsProcessed, loadRecentActivity } = useActions(externalDataSourcesLogic)

    useEffect(() => {
        if ((dataWarehouseSources?.results?.length || 0) > 0 || materializedViews.length > 0) {
            loadTotalRowsProcessed(materializedViews)
            loadRecentActivity(materializedViews)
        }
    }, [dataWarehouseSources?.results, materializedViews, loadTotalRowsProcessed, loadRecentActivity])

    const activityPagination = usePagination(recentActivity, { pageSize: LIST_SIZE }, 'activity')
    const sourcesPagination = usePagination(computedAllSources, { pageSize: LIST_SIZE }, 'sources')
    const viewsPagination = usePagination(materializedViews || [], { pageSize: LIST_SIZE }, 'views')

    const sourceColumns: any[] = [
        {
            title: 'Name',
            key: 'name',
            render: (_: any, source: DashboardDataSource) => (
                <div className="flex items-center gap-1">
                    <StatusIcon status={source.status ?? undefined} />
                    {source.url ? <LemonTableLink to={source.url} title={source.name} /> : <span>{source.name}</span>}
                </div>
            ),
        },
        { title: 'Type', dataIndex: 'type', key: 'type' },
        {
            title: 'Last sync',
            key: 'lastSync',
            render: (_: any, source: DashboardDataSource) =>
                source.lastSync ? <TZLabel time={source.lastSync} /> : '—',
        },
        {
            title: 'Rows',
            key: 'rowCount',
            align: 'right',
            render: (_: any, source: DashboardDataSource) =>
                source.rowCount !== null ? source.rowCount.toLocaleString() : '0',
        },
        {
            title: 'Status',
            key: 'status',
            align: 'right',
            render: (_: any, source: DashboardDataSource) =>
                source.status ? <StatusTag status={source.status} /> : '—',
        },
    ]

    const viewColumns: any[] = [
        {
            title: 'Name',
            key: 'name',
            render: (_: any, view: any) => (
                <div className="flex items-center gap-1">
                    <StatusIcon status={view.status} />
                    <LemonTableLink to={urls.sqlEditor(undefined, view.id)} title={view.name} />
                </div>
            ),
        },
        {
            title: 'Last run',
            key: 'last_run_at',
            render: (_: any, view: any) => (view.last_run_at ? <TZLabel time={view.last_run_at} /> : 'Never'),
        },
        {
            title: 'Rows',
            key: 'row_count',
            align: 'right',
            render: (_: any, view: any) =>
                view.row_count !== undefined && view.row_count !== null ? view.row_count.toLocaleString() : '0',
        },
        {
            title: 'Status',
            key: 'status',
            align: 'right',
            render: (_: any, view: any) => <StatusTag status={view.status} />,
        },
    ]

    const activityColumns: any[] = [
        {
            title: 'Activity',
            key: 'name',
            render: (_: any, activity: UnifiedRecentActivity) => (
                <div className="flex items-center gap-1">
                    <StatusIcon status={activity.status} />
                    {activity.sourceName && <span>{activity.sourceName}</span>}
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
            render: (_: any, activity: UnifiedRecentActivity) => <TZLabel time={activity.created_at} />,
        },
        {
            title: 'Rows',
            key: 'rowCount',
            align: 'right',
            render: (_: any, activity: UnifiedRecentActivity) =>
                activity.rowCount !== null ? activity.rowCount.toLocaleString() : '0',
        },
        {
            title: 'Status',
            key: 'status',
            align: 'right',
            render: (_: any, activity: UnifiedRecentActivity) => <StatusTag status={activity.status} />,
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
            ? 'danger'
            : s === 'warning'
              ? 'warning'
              : ['completed', 'success'].includes(s)
                ? 'success'
                : s === 'running'
                  ? 'none'
                  : 'muted'
        const size = ['completed', 'failed', 'error'].includes(s) ? 'medium' : 'small'

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

    const materializedCount = materializedViews.length
    const runningCount = materializedViews.filter((v) => v.status?.toLowerCase() === 'running').length

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
                        <div className="text-sm text-muted">Total Rows Processed</div>
                        <Tooltip
                            title="Total rows processed by all data sources and materialized views summed together"
                            placement="bottom"
                        >
                            <IconInfo className="text-muted mt-0.5" />
                        </Tooltip>
                    </div>
                    <div className="text-2xl font-semibold mt-1">{totalRowsProcessed.toLocaleString()}</div>
                </LemonCard>
                <LemonCard className="p-4 hover:transform-none">
                    <div className="text-sm text-muted">Materialized Views</div>
                    <div className="text-2xl font-semibold mt-1">{materializedCount}</div>
                    {runningCount > 0 && <div className="text-xs text-muted">{runningCount} running</div>}
                </LemonCard>
            </div>

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
                            dataSource={sourcesPagination.dataSourcePage as DashboardDataSource[]}
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
                            dataSource={activityPagination.dataSourcePage as UnifiedRecentActivity[]}
                            columns={activityColumns}
                            rowKey={(r) => `${r.type}-${r.name}-${r.created_at}`}
                        />
                        <PaginationControl {...activityPagination} nouns={['activity', 'activities']} />
                    </LemonCard>
                </div>

                <div>
                    <LemonCard className="p-4 hover:transform-none">
                        <h3 className="font-semibold mb-3">Quick Actions</h3>
                        <div className="space-y-2">
                            <LemonButton
                                to={`${urls.dataWarehouseSourceNew()}?kind=postgres`}
                                fullWidth
                                type="secondary"
                            >
                                Connect PostgreSQL
                            </LemonButton>
                            <LemonButton
                                to={`${urls.dataWarehouseSourceNew()}?kind=bigquery`}
                                fullWidth
                                type="secondary"
                            >
                                Connect BigQuery
                            </LemonButton>
                            <LemonButton to={`${urls.dataWarehouseSourceNew()}?kind=stripe`} fullWidth type="secondary">
                                Connect Stripe
                            </LemonButton>
                        </div>
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}
