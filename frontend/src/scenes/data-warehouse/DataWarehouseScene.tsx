import { useMemo } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PipelineTab } from '~/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { urls } from 'scenes/urls'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { IconPlusSmall, IconCheckCircle } from '@posthog/icons'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { dataWarehouseSettingsLogic } from './settings/dataWarehouseSettingsLogic'
import { dataWarehouseSceneLogic } from './settings/dataWarehouseSceneLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { billingLogic } from 'scenes/billing/billingLogic'
import { IconCancel, IconSync, IconExclamation, IconRadioButtonUnchecked } from 'lib/lemon-ui/icons'
import { availableSourcesDataLogic } from './new/availableSourcesDataLogic'
import { externalDataSourcesLogic } from './externalDataSourcesLogic'

export const scene: SceneExport = { component: DataWarehouseScene }

const LIST_SIZE = 5

interface SourceFieldConfig {
    name: string
    type: string
}

const getSourceType = (sourceType: string, availableSources?: Record<string, any> | null): 'Database' | 'API' => {
    const fields: SourceFieldConfig[] = availableSources?.[sourceType]?.fields || []
    if (fields.some((f) => f.name === 'connection_string' || ['host', 'port', 'database'].includes(f.name))) {
        return 'Database'
    }
    if (fields.some((f) => f.type === 'oauth' || ['api_key', 'access_token'].includes(f.name))) {
        return 'API'
    }
    return 'API'
}

interface DashboardDataSource {
    id: string
    name: string
    type: 'Database' | 'API'
    status: string | null
    lastSync: string | null
    rowCount: number | null
    url: string
}

interface DashboardActivity {
    name: string
    type: 'Materialization' | 'Data Sync'
    status: string
    time: string
    rowCount: number | null
    sourceName?: string
}

export function DataWarehouseScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources, selfManagedTables } = useValues(dataWarehouseSettingsLogic)
    const { materializedViews } = useValues(dataWarehouseSceneLogic)
    const { billing } = useValues(billingLogic)
    const { availableSources } = useValues(availableSourcesDataLogic)
    const { recentJobs } = useValues(externalDataSourcesLogic)

    const billingRowsSynced = billing?.products?.find((p) => p.type === 'rows_synced')?.current_usage || 0

    const calculatedRowsSynced = recentJobs.reduce((total, job) => total + (job.rows_synced || 0), 0)

    const lifetimeRowsSynced = billingRowsSynced || calculatedRowsSynced

    const recentActivity = useMemo((): DashboardActivity[] => {
        const items: DashboardActivity[] = []

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
        ;(recentJobs || []).forEach((job) => {
            const source = dataWarehouseSources?.results?.find((s) =>
                s.schemas?.some((schema) => schema.id === job.schema.id)
            )

            items.push({
                name: job.schema.name,
                type: 'Data Sync',
                status: job.status,
                time: job.created_at,
                rowCount: job.rows_synced,
                sourceName: source?.source_type,
            })
        })

        return items.sort((a, b) => new Date(b.time).valueOf() - new Date(a.time).valueOf())
    }, [materializedViews, recentJobs, dataWarehouseSources?.results])

    const allSources = useMemo(
        (): DashboardDataSource[] => [
            ...(dataWarehouseSources?.results || []).map((source): DashboardDataSource => {
                const sourceJobs = recentJobs.filter((job) =>
                    source.schemas?.some((schema) => schema.id === job.schema.id)
                )
                const totalRows = sourceJobs.reduce((sum, job) => sum + (job.rows_synced || 0), 0)
                const lastSync = sourceJobs.length > 0 ? sourceJobs[0].created_at : null

                return {
                    id: source.id,
                    name: source.source_type,
                    type: getSourceType(source.source_type, availableSources),
                    status: source.status,
                    lastSync,
                    rowCount: totalRows,
                    url: urls.dataWarehouseSource(`managed-${source.id}`),
                }
            }),
            ...selfManagedTables.map(
                (table): DashboardDataSource => ({
                    id: table.id,
                    name: table.name,
                    type: 'Database',
                    status: null,
                    lastSync: null,
                    rowCount: table.row_count ?? null,
                    url: urls.dataWarehouseSource(`self-managed-${table.id}`),
                })
            ),
        ],
        [dataWarehouseSources?.results, selfManagedTables, availableSources, recentJobs]
    )

    const activityPagination = usePagination(recentActivity, { pageSize: LIST_SIZE }, 'activity')
    const sourcesPagination = usePagination(allSources, { pageSize: LIST_SIZE }, 'sources')
    const viewsPagination = usePagination(materializedViews || [], { pageSize: LIST_SIZE }, 'views')

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
                    <div className="text-sm text-muted">Rows Synced (Lifetime)</div>
                    <div className="text-2xl font-semibold mt-1">{lifetimeRowsSynced.toLocaleString()}</div>
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
                                    {allSources.length} connected
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
                            {sourcesPagination.dataSourcePage.map((item) => (
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
                                                    : '0 rows'}
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
                            <PaginationControl {...sourcesPagination} nouns={['source', 'sources']} />
                        </div>
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center gap-2">
                            <h3 className="font-semibold text-xl">Views</h3>
                            <LemonTag size="medium" type="muted" className="mb-2 p-1 px-2 rounded-xl">
                                {materializedViews?.length || 0} views
                            </LemonTag>
                        </div>
                        <div className="space-y-2">
                            {viewsPagination.dataSourcePage.map((view) => (
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
                                                    : '0 rows'}
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
                            <PaginationControl {...viewsPagination} nouns={['view', 'views']} />
                        </div>
                    </LemonCard>

                    <LemonCard className="hover:transform-none">
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-xl">Recent Activity</h3>
                        </div>
                        <div className="space-y-2">
                            {activityPagination.dataSourcePage.map((activity) => (
                                <div
                                    key={`${activity.type}-${activity.name}-${activity.time}`}
                                    className="flex items-center justify-between border rounded p-2"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="font-medium text-base flex items-center gap-1">
                                            <StatusIcon status={activity.status} />
                                            {activity.sourceName && <span>{activity.sourceName} </span>}
                                            <span>{activity.name}</span>
                                            <LemonTag size="medium" type="muted" className="px-1 rounded-lg ml-1">
                                                {activity.type}
                                            </LemonTag>
                                        </div>
                                        <div className="text-xs text-muted mt-1">
                                            <TZLabel time={activity.time} />
                                        </div>
                                    </div>
                                    <div className="ml-4 text-right">
                                        <div className="text-xs text-muted mb-1">
                                            {activity.rowCount !== null
                                                ? `${activity.rowCount.toLocaleString()} rows`
                                                : '0 rows'}
                                        </div>
                                        <StatusTag status={activity.status} />
                                    </div>
                                </div>
                            ))}
                            <PaginationControl {...activityPagination} nouns={['activity', 'activities']} />
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
