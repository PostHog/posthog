import { useActions, useValues } from 'kea'
import { memo, useMemo } from 'react'
import type { ReactNode } from 'react'

import { IconRefresh } from '@posthog/icons'
import { TimeSeriesLineChart, createXAxisTickCallback } from '@posthog/quill-charts'
import type { TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes, percentage } from 'lib/utils/numbers'

import type {
    ManagedWarehouseMonitoringSeriesResponseApi,
    ManagedWarehouseMonitoringSnapshotResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { MONITORING_WINDOW_OPTIONS, managedWarehouseMonitoringLogic } from './managedWarehouseMonitoringLogic'
import type { MonitoringWorker } from './managedWarehouseMonitoringLogic'
import { buildMonitoringChartData } from './monitoringChartData'
import type { MonitoringChartMetricConfig } from './monitoringChartData'

const WORKER_STATE_TAGS: Record<string, LemonTagType> = {
    hot: 'success',
    hot_idle: 'success',
    idle: 'muted',
    reserved: 'primary',
    activating: 'warning',
    spawning: 'warning',
    draining: 'caution',
    lost: 'danger',
}

const WAREHOUSE_STATE_TAGS: Record<string, LemonTagType> = {
    ready: 'success',
    provisioning: 'warning',
    resharding: 'warning',
    deleting: 'caution',
    failed: 'danger',
}

function sentenceCase(value: string): string {
    const normalized = value.replaceAll('_', ' ')
    return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function MonitoringMetricCard({
    label,
    value,
    description,
    loading,
}: {
    label: string
    value: string
    description: string
    loading: boolean
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="min-h-32 p-4">
            <div className="text-sm font-semibold text-muted-alt">{label}</div>
            {loading ? (
                <LemonSkeleton className="my-3 h-8 w-24" />
            ) : (
                <div className="my-2 truncate text-3xl font-bold tabular-nums">{value}</div>
            )}
            <div className="text-xs text-muted">{description}</div>
        </LemonCard>
    )
}

function MonitoringChart({
    title,
    description,
    responses,
    metrics,
    yAxis,
    valueFormatter,
    loading,
}: {
    title: string
    description: string
    responses: ManagedWarehouseMonitoringSeriesResponseApi[]
    metrics: MonitoringChartMetricConfig[]
    yAxis?: TimeSeriesLineChartConfig['yAxis']
    valueFormatter?: (value: number) => string
    loading: boolean
}): JSX.Element {
    const theme = useChartTheme()
    const data = useMemo(() => buildMonitoringChartData(responses, metrics), [responses, metrics])
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: {
                timezone: 'UTC',
                tickFormatter: createXAxisTickCallback({ allDays: data.labels, timezone: 'UTC' }),
            },
            yAxis,
            legend: { show: data.series.length > 1, interactive: true, position: 'bottom' },
            tooltip: { placement: 'cursor', sortedByValue: true, valueFormatter },
        }),
        [data.labels, data.series.length, valueFormatter, yAxis]
    )

    return (
        <LemonCard hoverEffect={false} className="flex min-h-80 flex-col p-4">
            <div className="mb-4">
                <h3 className="mb-1">{title}</h3>
                <p className="mb-0 text-xs text-muted">{description}</p>
            </div>
            {loading && !data.labels.length ? (
                <LemonSkeleton className="h-64 w-full" />
            ) : data.labels.length && data.series.length ? (
                <div className="flex h-64 flex-col">
                    <TimeSeriesLineChart series={data.series} labels={data.labels} theme={theme} config={config} />
                </div>
            ) : (
                <div className="flex h-64 items-center justify-center text-muted">No data in this time range.</div>
            )}
        </LemonCard>
    )
}

function WorkerState({ worker }: { worker: MonitoringWorker }): JSX.Element {
    if (worker.session?.stalled) {
        return <LemonTag type="danger">Stalled</LemonTag>
    }
    return <LemonTag type={WORKER_STATE_TAGS[worker.state] ?? 'default'}>{sentenceCase(worker.state)}</LemonTag>
}

function SessionProgress({ worker }: { worker: MonitoringWorker }): JSX.Element {
    if (!worker.session) {
        return <span className="text-muted">No active session</span>
    }

    const progress = worker.session.percentage
    const rows = `${humanFriendlyNumber(worker.session.rows)} / ${humanFriendlyNumber(worker.session.total_rows)} rows`

    return (
        <div className="min-w-48 space-y-1">
            <div className="flex items-center justify-between gap-2 text-xs">
                <span>
                    {sentenceCase(worker.session.state)} via {worker.session.protocol}
                </span>
                <span className="text-muted">{humanFriendlyDuration(worker.session.elapsed_ms / 1000)}</span>
            </div>
            {progress !== null && progress >= 0 && <LemonProgress percent={Math.min(100, progress)} />}
            <div className="text-xs text-muted">{rows}</div>
        </div>
    )
}

const workerColumns: LemonTableColumns<MonitoringWorker> = [
    {
        title: 'Worker',
        dataIndex: 'id',
        render: (id) => (
            <code className="block max-w-48 truncate" title={String(id)}>
                {String(id)}
            </code>
        ),
    },
    {
        title: 'State',
        key: 'state',
        render: (_, worker) => <WorkerState worker={worker} />,
    },
    {
        title: 'Allocated resources',
        key: 'resources',
        render: (_, worker) => (
            <div>
                <div>{worker.cpu ? `${worker.cpu} CPU` : 'CPU unavailable'}</div>
                <div className="text-xs text-muted">
                    {worker.memory ? `${worker.memory} memory` : 'Memory unavailable'}
                </div>
            </div>
        ),
    },
    {
        title: 'Session',
        key: 'session',
        render: (_, worker) => <SessionProgress worker={worker} />,
    },
    {
        title: 'Created',
        dataIndex: 'created_at',
        render: (createdAt) => humanFriendlyDetailedTime(String(createdAt)),
    },
    {
        title: 'Last heartbeat',
        dataIndex: 'last_heartbeat_at',
        render: (lastHeartbeatAt) => humanFriendlyDetailedTime(lastHeartbeatAt ? String(lastHeartbeatAt) : null),
    },
]

function SummaryCards({
    snapshot,
    loading,
}: {
    snapshot: ManagedWarehouseMonitoringSnapshotResponseApi | null
    loading: boolean
}): JSX.Element {
    const workerValue = snapshot
        ? snapshot.limits.max_workers > 0
            ? `${snapshot.totals.workers} / ${snapshot.limits.max_workers}`
            : humanFriendlyNumber(snapshot.totals.workers)
        : '-'
    return (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
            <MonitoringMetricCard
                label="Workers"
                value={workerValue}
                description={
                    snapshot?.limits.max_workers === 0
                        ? 'Current workers. No organization-specific limit.'
                        : 'Current workers and organization limit'
                }
                loading={loading}
            />
            <MonitoringMetricCard
                label="Active sessions"
                value={snapshot ? humanFriendlyNumber(snapshot.totals.active_sessions) : '-'}
                description={
                    snapshot?.limits.max_vcpus === 0
                        ? 'Open sessions. No organization-specific vCPU admission limit.'
                        : `Open sessions. Admission limit: ${humanFriendlyNumber(snapshot?.limits.max_vcpus ?? 0)} active vCPUs.`
                }
                loading={loading}
            />
            <MonitoringMetricCard
                label="Running queries"
                value={snapshot ? humanFriendlyNumber(snapshot.totals.running_queries) : '-'}
                description="Queries currently running"
                loading={loading}
            />
            <MonitoringMetricCard
                label="Queued connections"
                value={snapshot ? humanFriendlyNumber(snapshot.totals.queued_connections) : '-'}
                description="Connections waiting for a worker"
                loading={loading}
            />
            <MonitoringMetricCard
                label="Allocated CPU"
                value={snapshot ? humanFriendlyNumber(snapshot.totals.allocated_cpu_cores) : '-'}
                description="Worker CPU cores currently allocated"
                loading={loading}
            />
            <MonitoringMetricCard
                label="Allocated memory"
                value={snapshot ? humanizeBytes(snapshot.totals.allocated_memory_bytes) : '-'}
                description="Worker memory currently allocated"
                loading={loading}
            />
        </div>
    )
}

function MonitoringSection({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="space-y-3">
            <div>
                <h2 className="mb-1">{title}</h2>
                <p className="mb-0 text-muted">{description}</p>
            </div>
            {children}
        </section>
    )
}

interface HistoricalMonitoringChartsProps {
    monitoringSeries: ManagedWarehouseMonitoringSeriesResponseApi[]
    initialLoading: boolean
}

const HistoricalMonitoringCharts = memo(function HistoricalMonitoringCharts({
    monitoringSeries,
    initialLoading,
}: HistoricalMonitoringChartsProps): JSX.Element {
    return (
        <>
            <MonitoringSection
                title="Query health"
                description="Query volume, failures, and duration for the selected time range."
            >
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                    <MonitoringChart
                        title="Query rate"
                        description="Queries per second, split by status and reason"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'query_rate', fallbackLabel: 'Queries' }]}
                        valueFormatter={(value) => `${humanFriendlyNumber(value)}/s`}
                        loading={initialLoading}
                    />
                    <MonitoringChart
                        title="Query error ratio"
                        description="Share of queries that returned an error"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'error_ratio', fallbackLabel: 'Errors' }]}
                        yAxis={{ format: 'percentage_scaled' }}
                        valueFormatter={(value) => percentage(value)}
                        loading={initialLoading}
                    />
                    <MonitoringChart
                        title="Query duration"
                        description="Median and p95 query duration"
                        responses={monitoringSeries}
                        metrics={[
                            { metric: 'duration_p50', fallbackLabel: 'p50' },
                            { metric: 'duration_p95', fallbackLabel: 'p95' },
                        ]}
                        yAxis={{ format: 'duration' }}
                        valueFormatter={(value) => humanFriendlyDuration(value, { secondsPrecision: 2 })}
                        loading={initialLoading}
                    />
                </div>
            </MonitoringSection>

            <MonitoringSection
                title="Capacity"
                description="Worker demand, connection wait time, and unexpected worker exits."
            >
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
                    <MonitoringChart
                        title="Active sessions"
                        description="Open sessions using warehouse capacity"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'sessions_active', fallbackLabel: 'Sessions' }]}
                        valueFormatter={(value) => humanFriendlyNumber(value)}
                        loading={initialLoading}
                    />
                    <MonitoringChart
                        title="Worker acquisition time"
                        description="p95 time to assign a worker, split by source"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'acquire_p95', fallbackLabel: 'Acquire p95' }]}
                        yAxis={{ format: 'duration' }}
                        valueFormatter={(value) => humanFriendlyDuration(value, { secondsPrecision: 2 })}
                        loading={initialLoading}
                    />
                    <MonitoringChart
                        title="Worker crash rate"
                        description="Unexpected worker exits per second"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'worker_crash_rate', fallbackLabel: 'Crashes' }]}
                        valueFormatter={(value) => `${humanFriendlyNumber(value)}/s`}
                        loading={initialLoading}
                    />
                </div>
            </MonitoringSection>

            <MonitoringSection title="Storage" description="Tracked warehouse storage over time.">
                <div className="grid grid-cols-1 gap-4">
                    <MonitoringChart
                        title="Tracked storage"
                        description="Current warehouse data stored in object storage"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'storage_bytes', fallbackLabel: 'Storage' }]}
                        yAxis={{ tickFormatter: (value: number) => humanizeBytes(value) }}
                        valueFormatter={humanizeBytes}
                        loading={initialLoading}
                    />
                </div>
            </MonitoringSection>
        </>
    )
})

export function MonitoringTab(): JSX.Element {
    const {
        monitoringSnapshot,
        monitoringSnapshotLoading,
        monitoringSnapshotError,
        monitoringSeries,
        initialMonitoringSeriesLoading,
        monitoringSeriesLoading,
        monitoringSeriesError,
        monitoringWindow,
        sortedWorkers,
    } = useValues(managedWarehouseMonitoringLogic)
    const { refreshMonitoring, setMonitoringWindow } = useActions(managedWarehouseMonitoringLogic)
    const initialLoading = monitoringSnapshotLoading && !monitoringSnapshot

    if (!monitoringSnapshot && monitoringSnapshotError) {
        return (
            <LemonBanner
                type="error"
                className="mt-4"
                action={{
                    children: 'Try again',
                    onClick: refreshMonitoring,
                    loading: monitoringSnapshotLoading || monitoringSeriesLoading,
                }}
            >
                Couldn't load warehouse monitoring. Refresh to try again.
            </LemonBanner>
        )
    }

    return (
        <div className="mt-4 space-y-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="mb-1 flex items-center gap-2">
                        <h2 className="mb-0">Warehouse monitoring</h2>
                        {monitoringSnapshot && (
                            <LemonTag type={WAREHOUSE_STATE_TAGS[monitoringSnapshot.warehouse.state] ?? 'default'}>
                                {sentenceCase(monitoringSnapshot.warehouse.state)}
                            </LemonTag>
                        )}
                    </div>
                    <p className="mb-0 text-muted">
                        View workers, query health, and resource usage across this organization.
                    </p>
                    {monitoringSnapshot && (
                        <p className="mb-0 mt-1 text-xs text-muted">
                            Updated {humanFriendlyDetailedTime(monitoringSnapshot.as_of)}
                        </p>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSegmentedButton
                        value={monitoringWindow}
                        onChange={setMonitoringWindow}
                        options={MONITORING_WINDOW_OPTIONS}
                        size="small"
                    />
                    <LemonButton
                        type="secondary"
                        icon={<IconRefresh />}
                        onClick={refreshMonitoring}
                        loading={monitoringSnapshotLoading || monitoringSeriesLoading}
                    >
                        Refresh
                    </LemonButton>
                </div>
            </div>

            {monitoringSnapshot && monitoringSnapshotError && (
                <LemonBanner type="warning">
                    Live worker data couldn't be refreshed. Showing the most recent available data.
                </LemonBanner>
            )}
            {monitoringSnapshot?.coverage.partial && (
                <LemonBanner type="warning">
                    Worker data is incomplete. {monitoringSnapshot.coverage.cp_responders} of{' '}
                    {monitoringSnapshot.coverage.cp_total} known control planes responded. Refresh to try again.
                </LemonBanner>
            )}
            {monitoringSeriesError && (
                <LemonBanner type="warning">
                    {monitoringSeries.length > 0
                        ? "Some historical metrics couldn't be refreshed. Available charts show the most recent data."
                        : "Historical metrics couldn't be loaded. Refresh to try again."}
                </LemonBanner>
            )}

            <SummaryCards snapshot={monitoringSnapshot} loading={initialLoading} />

            <HistoricalMonitoringCharts
                monitoringSeries={monitoringSeries}
                initialLoading={initialMonitoringSeriesLoading}
            />

            <MonitoringSection title="Workers" description="Current workers and their allocated resources.">
                <LemonTable
                    columns={workerColumns}
                    dataSource={sortedWorkers}
                    rowKey="id"
                    loading={initialLoading}
                    loadingSkeletonRows={3}
                    pagination={{ pageSize: 20 }}
                    emptyState="No workers are currently allocated. Run a query to start one."
                />
            </MonitoringSection>
        </div>
    )
}
