import { useEffect, useMemo, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PipelineTab } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { urls } from 'scenes/urls'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'
import { IconPlusSmall } from '@posthog/icons'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { dataWarehouseSettingsLogic } from './settings/dataWarehouseSettingsLogic'
import { dataWarehouseSceneLogic } from './settings/dataWarehouseSceneLogic'
import { dataWarehouseViewsLogic } from './saved_queries/dataWarehouseViewsLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { billingLogic } from 'scenes/billing/billingLogic'
import { fetchExternalDataSourceJobs } from './externalDataSourcesLogic'

export const scene: SceneExport = { component: DataWarehouseScene }

const LIST_SIZE = 5

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources, selfManagedTables } = useValues(dataWarehouseSettingsLogic)
    const { materializedViews } = useValues(dataWarehouseSceneLogic)

    const { dataWarehouseSavedQueries } = useValues(dataWarehouseViewsLogic)
    const { billing } = useValues(billingLogic)

    const monthlyRowsSynced = billing?.products?.find((p) => p.type === 'rows_synced')?.current_usage || 0

    type Activity = { name: string; type: 'Materialization' | 'Sync'; status?: string; time: string; rows?: number }
    const [recentActivity, setRecentActivity] = useState<Activity[]>([])
    const [activityPage, setActivityPage] = useState(0)

    const sourcesForJobs = useMemo(
        () =>
            (dataWarehouseSources?.results || [])
                .slice(0, LIST_SIZE)
                .map((s: any) => ({ id: s.id, source_type: s.source_type })),
        [dataWarehouseSources?.results]
    )

    useEffect(() => {
        let cancelled = false
        const load = async (): Promise<void> => {
            const items: Activity[] = []
            for (const view of materializedViews) {
                if (view.last_run_at) {
                    const vStatus = (view as any).status as string | undefined
                    items.push({
                        name: view.name,
                        type: 'Materialization',
                        status: vStatus,
                        time: String(view.last_run_at),
                        rows: vStatus && vStatus.toLowerCase() === 'failed' ? 0 : undefined,
                    })
                }
            }
            const jobGroups = await Promise.all(
                sourcesForJobs.map(async (s: any) => {
                    try {
                        const jobs: any[] = await fetchExternalDataSourceJobs(s.id, null, null)
                        return jobs.slice(0, 3).map((j: any) => ({
                            name: j.schema?.name ? `${j.schema.name} (${s.source_type})` : `${s.source_type} schema`,
                            type: 'Sync' as const,
                            status: j.status,
                            time: String(j.created_at),
                            rows: typeof j.rows_synced === 'number' ? j.rows_synced : undefined,
                        }))
                    } catch {
                        return [] as Activity[]
                    }
                })
            )
            items.push(...jobGroups.flat())

            items.sort((a, b) => new Date(b.time).valueOf() - new Date(a.time).valueOf())
            if (!cancelled) {
                setRecentActivity(items)
                setActivityPage(0)
            }
        }
        void load()
        return () => {
            cancelled = true
        }
    }, [materializedViews, sourcesForJobs])

    const pageSize = LIST_SIZE
    const totalPages = Math.max(1, Math.ceil(recentActivity.length / pageSize))
    const pageItems = recentActivity.slice(activityPage * pageSize, activityPage * pageSize + pageSize)

    const StatusTag = ({ status }: { status?: string }): JSX.Element => {
        const s = (status || '').toLowerCase()
        const t =
            s === 'failed' || s === 'error'
                ? 'danger'
                : s === 'warning'
                  ? 'warning'
                  : s === 'completed' || s === 'success'
                    ? 'success'
                    : s === 'running'
                      ? 'primary'
                      : 'muted'
        const size: 'small' | 'medium' = s === 'completed' || s === 'failed' || s === 'error' ? 'medium' : 'small'
        return (
            <LemonTag size={size} type={t}>
                {s || '—'}
            </LemonTag>
        )
    }

    if (!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]) {
        return <NotFound object="Data Warehouse" />
    }

    const materializedCount = materializedViews.length
    const runningCount = materializedViews.filter((v) => (v as any).status === 'Running').length
    const viewsWithStatus = (dataWarehouseSavedQueries || []).filter((v) => v.status)

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-semibold">Data Warehouse</h1>
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
                <LemonCard className="p-4">
                    <div className="text-sm text-muted">Rows Synced (MTD)</div>
                    <div className="text-2xl font-semibold mt-1">{monthlyRowsSynced.toLocaleString()}</div>
                </LemonCard>
                <LemonCard className="p-4">
                    <div className="text-sm text-muted">Materialized Views</div>
                    <div className="text-2xl font-semibold mt-1">{materializedCount}</div>
                    {runningCount > 0 && <div className="text-xs text-muted">{runningCount} running</div>}
                </LemonCard>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <div className="lg:col-span-2 space-y-2">
                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2">
                                <h3 className="font-semibold text-xl">Data Sources</h3>
                                <LemonTag size="medium" type="muted" className="mb-2 p-1 px-2 rounded-xl">
                                    {(dataWarehouseSources?.results?.length || 0) + selfManagedTables.length} connected
                                </LemonTag>
                            </div>
                            <LemonButton to={urls.pipeline(PipelineTab.Sources)} size="small" type="secondary">
                                View All
                            </LemonButton>
                        </div>
                        <div className="space-y-2">
                            {[
                                ...(dataWarehouseSources?.results || []).map((source) => ({
                                    id: source.id,
                                    name: source.source_type,
                                    status: source.status,
                                    lastSync: source.last_run_at,
                                    url: urls.dataWarehouseSource(`managed-${source.id}`),
                                })),
                                ...selfManagedTables.map((table) => ({
                                    id: table.id,
                                    name: table.name,
                                    status: null,
                                    lastSync: null,
                                    url: urls.dataWarehouseSource(`self-managed-${table.id}`),
                                })),
                            ]
                                .slice(0, LIST_SIZE)
                                .map((item) => (
                                    <div
                                        key={item.id}
                                        className="flex items-center justify-between p-2 border rounded p-2"
                                    >
                                        <div className="flex-1 min-w-0 ">
                                            <div className="font-medium text-sm">{item.name}</div>
                                            <div className="text-xs text-muted mt-1">
                                                Last sync: {item.lastSync ? <TZLabel time={item.lastSync} /> : '—'}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2 ml-4">
                                            {item.status ? (
                                                <StatusTag status={item.status} />
                                            ) : (
                                                <span className="text-xs text-muted">—</span>
                                            )}
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
                            {viewsWithStatus.slice(0, LIST_SIZE).map((view) => (
                                <div key={view.id} className="flex items-center justify-between border rounded p-2">
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-sm">{view.name}</div>
                                        <div className="text-xs text-muted mt-1">
                                            Last run: {view.last_run_at ? <TZLabel time={view.last_run_at} /> : 'Never'}
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2 ml-4">
                                        <StatusTag status={view.status} />
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
                                        <div className="font-medium text-sm">{activity.name}</div>
                                        <div className="text-xs text-muted mt-1">
                                            {activity.type} • <TZLabel time={activity.time} />
                                        </div>
                                    </div>
                                    <div className="ml-4 text-right">
                                        <div className="text-xs text-muted mb-1">
                                            {typeof activity.rows === 'number'
                                                ? `${activity.rows.toLocaleString()} rows`
                                                : '—'}
                                        </div>
                                        <StatusTag status={activity.status} />
                                    </div>
                                </div>
                            ))}
                            <div className="flex items-center justify-end gap-2">
                                <span className="text-xs text-muted">
                                    Page {Math.min(activityPage + 1, totalPages)} / {totalPages}
                                </span>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    disabled={activityPage <= 0}
                                    onClick={() => setActivityPage((p) => Math.max(0, p - 1))}
                                >
                                    Prev
                                </LemonButton>
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
                    </LemonCard>
                </div>

                <div>
                    <LemonCard className="p-4">
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
                            <LemonButton to={`${urls.dataWarehouseSourceNew()}?kind=csv`} fullWidth type="secondary">
                                Import CSV
                            </LemonButton>
                        </div>
                    </LemonCard>
                </div>
            </div>
        </div>
    )
}
