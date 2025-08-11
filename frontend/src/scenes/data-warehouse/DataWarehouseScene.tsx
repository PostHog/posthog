import { useMemo, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PipelineTab } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { urls } from 'scenes/urls'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'
import { IconPlusSmall, IconCheckCircle } from '@posthog/icons'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { dataWarehouseSettingsLogic } from './settings/dataWarehouseSettingsLogic'
import { dataWarehouseSceneLogic } from './settings/dataWarehouseSceneLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { IconCancel, IconSync, IconExclamation, IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'

export const scene: SceneExport = { component: DataWarehouseScene }

const LIST_SIZE = 5

// Helper function to classify data sources
const getSourceType = (sourceType: string): 'Database' | 'API' => {
    const databases = ['Postgres', 'MySQL', 'MSSQL', 'Snowflake', 'BigQuery', 'Redshift', 'MongoDB']
    return databases.includes(sourceType) ? 'Database' : 'API'
}

// Type-safe interfaces following PostHog patterns
interface DashboardDataSource {
    id: string
    name: string
    type: 'Database' | 'API'
    status: string | null
    lastSync: Dayjs | null
    rowCount: number | null
    url: string
}

interface DashboardActivity {
    name: string
    type: 'Materialization' | 'Sync'
    status: string
    time: string
    rowCount: number | null
}

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources, selfManagedTables } = useValues(dataWarehouseSettingsLogic)
    const { materializedViews } = useValues(dataWarehouseSceneLogic)
    const { billing } = useValues(billingLogic)

    const monthlyRowsSynced = billing?.products?.find((p) => p.type === 'rows_synced')?.current_usage || 0

    // Type-safe recent activity transformation following PostHog selector pattern
    const recentActivity = useMemo((): DashboardActivity[] => {
        const items: DashboardActivity[] = []

        // Materialized view activities
        materializedViews.forEach((view) => {
            if (view.last_run_at) {
                items.push({
                    name: view.name,
                    type: 'Materialization',
                    status: view.status || 'unknown',
                    time: String(view.last_run_at),
                    rowCount: view.row_count ?? null,
                })
            }
        })

        // Schema sync activities
        dataWarehouseSources?.results?.forEach((source) => {
            source.schemas?.forEach((schema) => {
                if (schema.should_sync) {
                    items.push({
                        name: `${schema.name} (${source.source_type})`,
                        type: 'Sync',
                        status: schema.status || 'completed',
                        time: schema.last_synced_at
                            ? String(schema.last_synced_at)
                            : String(source.last_run_at || new Date().toISOString()),
                        rowCount: null, // Schema row counts not available in this interface
                    })
                }
            })
        })

        return items.sort((a, b) => new Date(b.time).valueOf() - new Date(a.time).valueOf())
    }, [materializedViews, dataWarehouseSources?.results])

    const [activityPage, setActivityPage] = useState(0)
    const [sourcesPage, setSourcesPage] = useState(0)
    const [viewsPage, setViewsPage] = useState(0)
    const [viewsSearchTerm] = useState('')
    // setViewsSearchTerm intentionally removed to simplify type safety implementation

    const pageSize = LIST_SIZE
    const totalPages = Math.max(1, Math.ceil(recentActivity.length / pageSize))
    const pageItems = recentActivity.slice(activityPage * pageSize, activityPage * pageSize + pageSize)

    // Type-safe data sources transformation following PostHog selector pattern
    const allSources = useMemo(
        (): DashboardDataSource[] => [
            // Managed data sources
            ...(dataWarehouseSources?.results || []).map(
                (source): DashboardDataSource => ({
                    id: source.id,
                    name: source.source_type,
                    type: getSourceType(source.source_type),
                    status: source.status,
                    lastSync: source.last_run_at ?? null,
                    rowCount: null, // External data source row counts handled at schema level
                    url: urls.dataWarehouseSource(`managed-${source.id}`),
                })
            ),
            // Self-managed tables
            ...selfManagedTables.map(
                (table): DashboardDataSource => ({
                    id: table.id,
                    name: table.name,
                    type: 'Database', // Self-managed are typically database tables
                    status: null,
                    lastSync: null,
                    rowCount: table.row_count ?? null,
                    url: urls.dataWarehouseSource(`self-managed-${table.id}`),
                })
            ),
        ],
        [dataWarehouseSources?.results, selfManagedTables]
    )
    const sourcesTotalPages = Math.max(1, Math.ceil(allSources.length / pageSize))
    const pageSources = allSources.slice(sourcesPage * pageSize, sourcesPage * pageSize + pageSize)
    const viewsWithStatus = useMemo(() => {
        const views = materializedViews || []
        if (!viewsSearchTerm.trim()) {
            return views
        }
        const normalizedSearch = viewsSearchTerm.toLowerCase()
        return views.filter((view) => view.name.toLowerCase().includes(normalizedSearch))
    }, [materializedViews, viewsSearchTerm])

    const viewsTotalPages = Math.max(1, Math.ceil(viewsWithStatus.length / pageSize))
    const pageViews = viewsWithStatus.slice(viewsPage * pageSize, viewsPage * pageSize + pageSize)

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
                  ? 'primary'
                  : 'muted'
        const size = ['completed', 'failed', 'error'].includes(s) ? 'medium' : 'small'

        return (
            <LemonTag size={size} type={type}>
                {s || '—'}
            </LemonTag>
        )
    }

    const materializedCount = materializedViews.length
    const runningCount = materializedViews.filter((v) => v.status === 'Running').length

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
                    <div className="text-sm text-muted">Rows Synced (MTD)</div>
                    <div className="text-2xl font-semibold mt-1">{monthlyRowsSynced.toLocaleString()}</div>
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
                                    {(dataWarehouseSources?.results?.length || 0) + selfManagedTables.length} connected
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
                        <div className="space-y-2">
                            {pageSources.map((item) => (
                                <div key={item.id} className="flex items-center justify-between p-2 border rounded">
                                    <div className="flex-1 min-w-0 ">
                                        <div className="font-medium text-base flex items-center gap-1">
                                            <StatusIcon status={item.status ?? undefined} />
                                            <span>{item.name}</span>
                                        </div>
                                        <div className="text-xs text-muted mt-1">
                                            {item.type} • Last sync:{' '}
                                            {item.lastSync ? <TZLabel time={item.lastSync} /> : '—'}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2 ml-4">
                                        <div className="text-right">
                                            <div className="text-xs text-muted mb-1">
                                                {item.rowCount !== null
                                                    ? `${item.rowCount.toLocaleString()} rows`
                                                    : 'No row data'}
                                            </div>
                                            {item.status ? (
                                                <StatusTag status={item.status} />
                                            ) : (
                                                <span className="text-xs text-muted">—</span>
                                            )}
                                        </div>
                                        {item.url && (
                                            <LemonButton
                                                to={item.url}
                                                targetBlank
                                                size="xsmall"
                                                type="tertiary"
                                                icon={<IconOpenInNew />}
                                            />
                                        )}
                                    </div>
                                </div>
                            ))}
                            {sourcesTotalPages > 1 && (
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-muted">
                                        Showing {sourcesPage * pageSize + 1} to{' '}
                                        {Math.min((sourcesPage + 1) * pageSize, allSources.length)} of{' '}
                                        {allSources.length} sources
                                    </span>
                                    <div className="flex items-center gap-2">
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            disabled={sourcesPage <= 0}
                                            onClick={() => setSourcesPage((p) => Math.max(0, p - 1))}
                                        >
                                            Previous
                                        </LemonButton>
                                        <span className="text-xs text-muted">
                                            Page {sourcesPage + 1} of {sourcesTotalPages}
                                        </span>
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            disabled={sourcesPage >= sourcesTotalPages - 1}
                                            onClick={() =>
                                                setSourcesPage((p) => Math.min(sourcesTotalPages - 1, p + 1))
                                            }
                                        >
                                            Next
                                        </LemonButton>
                                    </div>
                                </div>
                            )}
                        </div>
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center gap-2">
                            <h3 className="font-semibold text-xl">Views</h3>
                            <LemonTag size="medium" type="muted" className="mb-2 p-1 px-2 rounded-xl">
                                {viewsWithStatus.length} views
                            </LemonTag>
                        </div>
                        <div className="space-y-2">
                            {pageViews.map((view) => (
                                <div key={view.id} className="flex items-center justify-between border rounded p-2">
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-base flex items-center gap-1">
                                            <StatusIcon status={view.status} />
                                            <span>{view.name}</span>
                                        </div>
                                        <div className="text-xs text-muted mt-1">
                                            Last run: {view.last_run_at ? <TZLabel time={view.last_run_at} /> : 'Never'}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2 ml-4">
                                        <div className="text-right">
                                            <div className="text-xs text-muted mb-1">
                                                {view.row_count !== undefined && view.row_count !== null
                                                    ? `${view.row_count.toLocaleString()} rows`
                                                    : 'No row data'}
                                            </div>
                                            <StatusTag status={view.status} />
                                        </div>
                                        <LemonButton
                                            to={urls.sqlEditor(undefined, view.id)}
                                            targetBlank
                                            size="xsmall"
                                            type="tertiary"
                                            icon={<IconOpenInNew />}
                                        />
                                    </div>
                                </div>
                            ))}
                            {viewsTotalPages > 1 && (
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-muted">
                                        Showing {viewsPage * pageSize + 1} to{' '}
                                        {Math.min((viewsPage + 1) * pageSize, viewsWithStatus.length)} of{' '}
                                        {viewsWithStatus.length} views
                                    </span>
                                    <div className="flex items-center gap-2">
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            disabled={viewsPage <= 0}
                                            onClick={() => setViewsPage((p) => Math.max(0, p - 1))}
                                        >
                                            Previous
                                        </LemonButton>
                                        <span className="text-xs text-muted">
                                            Page {viewsPage + 1} of {viewsTotalPages}
                                        </span>
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            disabled={viewsPage >= viewsTotalPages - 1}
                                            onClick={() => setViewsPage((p) => Math.min(viewsTotalPages - 1, p + 1))}
                                        >
                                            Next
                                        </LemonButton>
                                    </div>
                                </div>
                            )}
                        </div>
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-xl">Recent Activity</h3>
                        </div>
                        <div className="space-y-2">
                            {pageItems.map((activity) => (
                                <div
                                    key={`${activity.type}-${activity.name}-${activity.time}`}
                                    className="flex items-center justify-between border rounded p-2"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-base flex items-center gap-1">
                                            <StatusIcon status={activity.status} />
                                            <span>{activity.name}</span>
                                        </div>
                                        <div className="text-xs text-muted mt-1">
                                            {activity.type} • <TZLabel time={activity.time} />
                                        </div>
                                    </div>
                                    <div className="ml-4 text-right">
                                        <div className="text-xs text-muted mb-1">
                                            {activity.rowCount !== null
                                                ? `${activity.rowCount.toLocaleString()} rows`
                                                : 'No row data'}
                                        </div>
                                        <StatusTag status={activity.status} />
                                    </div>
                                </div>
                            ))}
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-muted">
                                    Showing {activityPage * pageSize + 1} to{' '}
                                    {Math.min((activityPage + 1) * pageSize, recentActivity.length)} of{' '}
                                    {recentActivity.length} activities
                                </span>
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        disabled={activityPage <= 0}
                                        onClick={() => setActivityPage((p) => Math.max(0, p - 1))}
                                    >
                                        Previous
                                    </LemonButton>
                                    <span className="text-xs text-muted">
                                        Page {activityPage + 1} of {totalPages}
                                    </span>
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        disabled={activityPage >= totalPages - 1}
                                        onClick={() => setActivityPage((p) => Math.min(totalPages - 1, p + 1))}
                                    >
                                        Next
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
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
