import { isNodeWithSource } from '~/queries/schema/node-guards'
import { NodeKind } from '~/queries/schema/schema-general'
import { DashboardTile } from '~/types'

export type LiveExecutionClass = 'telemetry_metrics' | 'telemetry_logs' | 'telemetry_traces'

export const LIVE_INTERVAL_OPTIONS: readonly number[] = [5, 10, 30, 60]

// Mirrors LIVE_CACHE_AGE_SECONDS in posthog/hogql_queries/execution_class.py. Metrics land in
// ClickHouse in 30 s blocks, so asking for fresher metrics recomputes identical data.
export const LIVE_CACHE_AGE_SECONDS: Record<LiveExecutionClass, number> = {
    telemetry_metrics: 30,
    telemetry_logs: 5,
    telemetry_traces: 5,
}

const CLASS_BY_QUERY_KIND: Partial<Record<NodeKind, LiveExecutionClass>> = {
    [NodeKind.MetricsQuery]: 'telemetry_metrics',
    [NodeKind.MetricsHistogramQuery]: 'telemetry_metrics',
}

const CLASS_BY_WIDGET_TYPE: Record<string, LiveExecutionClass> = {
    metrics_table: 'telemetry_metrics',
    logs_list: 'telemetry_logs',
}

export function liveExecutionClassForTile(tile: DashboardTile): LiveExecutionClass | null {
    if (tile.widget) {
        return CLASS_BY_WIDGET_TYPE[tile.widget.widget_type] ?? null
    }
    const query = tile.insight?.query
    const source = isNodeWithSource(query) ? query.source : query
    return (source?.kind && CLASS_BY_QUERY_KIND[source.kind as NodeKind]) || null
}

export function clampLiveInterval(value: unknown): number | null {
    return typeof value === 'number' && LIVE_INTERVAL_OPTIONS.includes(value) ? value : null
}

export interface LiveRefreshCandidates {
    tiles: DashboardTile[]
    now: number
    intervalSeconds: number
    inFlightTileIds: ReadonlySet<number>
    // Collapsed groups and inactive tabs: their tiles do not load, so a live tick skips them too.
    hiddenTileIds: ReadonlySet<number>
    // Client time when each tile's last live response arrived.
    receivedAt: Readonly<Record<number, number>>
}

export function tilesDueForLiveRefresh({
    tiles,
    now,
    intervalSeconds,
    inFlightTileIds,
    hiddenTileIds,
    receivedAt,
}: LiveRefreshCandidates): number[] {
    const intervalMs = intervalSeconds * 1000
    return tiles
        .filter((tile) => {
            const executionClass = liveExecutionClassForTile(tile)
            if (!executionClass || inFlightTileIds.has(tile.id) || hiddenTileIds.has(tile.id)) {
                return false
            }
            const answeredAt = receivedAt[tile.id]
            if (answeredAt !== undefined && now - answeredAt < intervalMs) {
                return false
            }
            const lastRefresh = tile.insight?.last_refresh
            if (!lastRefresh) {
                return true
            }
            const cacheAgeMs = Math.max(intervalSeconds, LIVE_CACHE_AGE_SECONDS[executionClass]) * 1000
            return now - Date.parse(lastRefresh) >= cacheAgeMs
        })
        .map((tile) => tile.id)
}
