import type { DashboardSharingDebugApi } from './generated/api.schemas'

export interface DashboardSharingDebugRun {
    batchId: string
    status: 'running' | 'complete' | 'partial' | 'aborted' | 'skipped'
    reason?: string
    tiles: { id: number; name: string }[]
    results: Record<number, { cached: boolean; failed: boolean; debug?: DashboardSharingDebugApi }>
}

export function summarizeSharingDebug(run: DashboardSharingDebugRun): {
    queryCount: number
    rowsRead: number
    durationMs: number
    sharedGroups: number
    combinedQueries: number
    cachedTiles: number
    receivedTiles: number
    truncated: boolean
} {
    const results = Object.values(run.results)
    const diagnostics = results.flatMap((result) => (result.debug ? [result.debug] : []))
    const shared = diagnostics.flatMap((debug) => debug.executions.filter((entry) => entry.outcome === 'shared'))
    return {
        queryCount: diagnostics.reduce((sum, debug) => sum + debug.query_count, 0),
        rowsRead: diagnostics.reduce((sum, debug) => sum + debug.rows_read, 0),
        durationMs: diagnostics.reduce((sum, debug) => sum + debug.duration_ms, 0),
        sharedGroups: shared.length,
        combinedQueries: shared.reduce((sum, execution) => sum + execution.tile_ids.length, 0),
        cachedTiles: results.filter((result) => result.cached).length,
        receivedTiles: results.length,
        truncated: diagnostics.some((debug) => debug.truncated),
    }
}
