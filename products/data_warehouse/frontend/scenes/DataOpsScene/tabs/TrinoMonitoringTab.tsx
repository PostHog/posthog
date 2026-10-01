import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanizeBytes } from 'lib/utils/numbers'

import {
    TRINO_MONITORING_WINDOW_OPTIONS,
    managedWarehouseTrinoMonitoringLogic,
} from './managedWarehouseTrinoMonitoringLogic'
import type { TrinoMonitoringQuery } from './managedWarehouseTrinoMonitoringLogic'
import { MonitoringSection } from './MonitoringSection'
import { TrinoHistoricalCharts } from './TrinoHistoricalCharts'
import { duration, stateLabel } from './trinoMonitoringFormat'
import { TrinoMonitoringSummaryCards } from './TrinoMonitoringSummaryCards'
import { TrinoQueryDetails } from './TrinoQueryDetails'

const LONG_RUNNING_MS = 5 * 60 * 1000

const TRINO_STATE_TAGS: Record<string, LemonTagType> = {
    ready: 'success',
    pending: 'warning',
    provisioning: 'warning',
    failed: 'danger',
}

const QUERY_STATE_TAGS: Record<string, LemonTagType> = {
    running: 'success',
    finishing: 'success',
    queued: 'warning',
}

function QueryState({ query }: { query: TrinoMonitoringQuery }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-1">
            <LemonTag type={QUERY_STATE_TAGS[query.state] ?? 'primary'}>{stateLabel(query.state)}</LemonTag>
            {query.blocked && <LemonTag type="caution">Blocked</LemonTag>}
            {query.elapsed_ms >= LONG_RUNNING_MS && <LemonTag type="warning">Long running</LemonTag>}
        </div>
    )
}

function QueryProgress({ query }: { query: TrinoMonitoringQuery }): JSX.Element {
    const progress = query.progress_percentage
    if (progress === null || progress === undefined) {
        return <span className="text-muted">Not available</span>
    }
    return (
        <div className="min-w-24">
            <LemonProgress percent={Math.min(100, progress)} />
        </div>
    )
}

const queryColumns: LemonTableColumns<TrinoMonitoringQuery> = [
    {
        title: 'State',
        key: 'state',
        render: (_, query) => <QueryState query={query} />,
    },
    {
        title: 'User',
        dataIndex: 'user',
        render: (user) => (user ? String(user) : <span className="text-muted">Unknown</span>),
    },
    {
        title: 'Query',
        dataIndex: 'query',
        render: (text) => (
            <code className="block max-w-80 truncate" title={String(text)}>
                {String(text)}
            </code>
        ),
    },
    {
        title: 'Elapsed',
        dataIndex: 'elapsed_ms',
        render: (elapsed) => duration(Number(elapsed)),
    },
    {
        title: 'Data scanned',
        dataIndex: 'physical_input_bytes',
        render: (bytes) => humanizeBytes(Number(bytes)),
    },
    {
        title: 'Progress',
        key: 'progress',
        render: (_, query) => <QueryProgress query={query} />,
    },
]

export function TrinoMonitoringTab(): JSX.Element {
    const {
        monitoringSnapshot,
        monitoringSnapshotLoading,
        monitoringSnapshotError,
        monitoringSeries,
        initialMonitoringSeriesLoading,
        monitoringSeriesLoading,
        monitoringSeriesError,
        monitoringWindow,
    } = useValues(managedWarehouseTrinoMonitoringLogic)
    const { refreshMonitoring, setMonitoringWindow } = useActions(managedWarehouseTrinoMonitoringLogic)
    const initialLoading = monitoringSnapshotLoading && !monitoringSnapshot
    const liveDataUnavailable = !!monitoringSnapshot && !monitoringSnapshot.available

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
                            <LemonTag type={TRINO_STATE_TAGS[monitoringSnapshot.trino.state] ?? 'default'}>
                                {stateLabel(monitoringSnapshot.trino.state)}
                            </LemonTag>
                        )}
                    </div>
                    <p className="mb-0 text-muted">
                        View query activity, performance, and storage for this organization.
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
                        options={TRINO_MONITORING_WINDOW_OPTIONS}
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
                    Live query data couldn't be refreshed. Showing the most recent available data.
                </LemonBanner>
            )}
            {liveDataUnavailable && (
                <LemonBanner type="warning">
                    Live query data is temporarily unavailable. Historical charts may still be up to date.
                </LemonBanner>
            )}
            {monitoringSeriesError && (
                <LemonBanner type="warning">
                    {monitoringSeries.length > 0
                        ? "Some historical metrics couldn't be refreshed. Available charts show the most recent data."
                        : "Historical metrics couldn't be loaded. Refresh to try again."}
                </LemonBanner>
            )}

            <TrinoMonitoringSummaryCards snapshot={monitoringSnapshot} loading={initialLoading} />

            <TrinoHistoricalCharts
                monitoringSeries={monitoringSeries}
                initialLoading={initialMonitoringSeriesLoading}
            />

            <MonitoringSection
                title="Queries in flight"
                description="Queries submitted to the warehouse and not yet finished."
            >
                <LemonTable
                    columns={queryColumns}
                    dataSource={monitoringSnapshot?.queries ?? []}
                    rowKey="query_id"
                    loading={initialLoading}
                    loadingSkeletonRows={3}
                    pagination={{ pageSize: 20 }}
                    expandable={{
                        expandedRowRender: (query) => <TrinoQueryDetails query={query} />,
                        noIndent: true,
                    }}
                    emptyState={
                        liveDataUnavailable
                            ? 'Live query data is not available right now.'
                            : 'No queries are running right now.'
                    }
                />
                {monitoringSnapshot?.queries_truncated && (
                    <p className="mb-0 text-xs text-muted">Showing the 200 longest-running queries.</p>
                )}
            </MonitoringSection>
        </div>
    )
}
