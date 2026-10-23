import { humanFriendlyNumber, humanizeBytes } from 'lib/utils/numbers'

import type { ManagedWarehouseTrinoMonitoringSnapshotResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { MonitoringMetricCard } from './MonitoringMetricCard'
import { duration, withLimit } from './trinoMonitoringFormat'

export function TrinoMonitoringSummaryCards({
    snapshot,
    loading,
}: {
    snapshot: ManagedWarehouseTrinoMonitoringSnapshotResponseApi | null
    loading: boolean
}): JSX.Element {
    // Totals are zero when live data is unavailable. A dash keeps that from reading as an idle warehouse.
    const live = snapshot?.available ? snapshot : null
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-3 @md:grid-cols-2 @4xl:grid-cols-3 @7xl:grid-cols-6">
                <MonitoringMetricCard
                    label="Queries in flight"
                    value={live ? humanFriendlyNumber(live.totals.in_flight) : '-'}
                    description="Queries submitted and not yet finished"
                    loading={loading}
                />
                <MonitoringMetricCard
                    label="Running"
                    value={live ? withLimit(live.totals.running, live.limits.max_running_queries) : '-'}
                    description={
                        live && live.limits.max_running_queries > 0
                            ? 'Queries past the queue, and how many can run at once'
                            : 'Queries past the queue'
                    }
                    loading={loading}
                />
                <MonitoringMetricCard
                    label="Queued"
                    value={live ? withLimit(live.totals.queued, live.limits.max_queued_queries) : '-'}
                    description="Queries waiting for a running slot"
                    loading={loading}
                />
                <MonitoringMetricCard
                    label="Blocked"
                    value={live ? humanFriendlyNumber(live.totals.blocked) : '-'}
                    description="Running queries waiting on data or metadata"
                    loading={loading}
                />
                <MonitoringMetricCard
                    label="Longest running"
                    value={live ? duration(live.totals.longest_running_ms) : '-'}
                    description="Longest in-flight query"
                    loading={loading}
                />
                <MonitoringMetricCard
                    label="Data scanned"
                    value={live ? humanizeBytes(live.totals.physical_input_bytes) : '-'}
                    description="Read so far by in-flight queries"
                    loading={loading}
                />
            </div>
        </div>
    )
}
