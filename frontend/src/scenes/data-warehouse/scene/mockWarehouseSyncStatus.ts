import { dayjs } from 'lib/dayjs'

// Backend-neutral "warehouse data freshness" contract. Both the current Dagster daily-partition
// backfill and the future viaduck CDC replication map onto this same shape, so the UI never speaks
// either backend's vocabulary. This mock stands in for the API response until the provider seam ships.

export type WarehouseSyncBackend = 'dagster' | 'viaduck'
export type WarehouseSyncState = 'seeding' | 'caught_up' | 'lagging' | 'error' | 'not_started'

export interface WarehouseSyncStatus {
    /** Which pipeline is moving data right now. Informational — the UI renders the same regardless. */
    backend: WarehouseSyncBackend
    state: WarehouseSyncState
    /** ISO timestamp the warehouse is fresh through (the headline). Null before any data lands. */
    freshThrough: string | null
    /** How far behind "now"/source the data is, in seconds. Null when unknown. */
    lagSeconds: number | null
    /** Last time the pipeline made forward progress. */
    lastActivityAt: string | null
    /** The one-time historical load (Dagster: partition range; viaduck: scan-based seeding). */
    initialBackfill: { complete: boolean; progressPct: number | null }
    /** Cumulative events moved into the warehouse. */
    totalRowsSynced: number | null
    error: { message: string; since: string } | null
    updatedAt: string
}

export function getMockWarehouseSyncStatus(): WarehouseSyncStatus {
    const now = dayjs()
    // Dagster runs daily with end_offset=0, so "fresh through yesterday" is the steady state.
    const freshThrough = now.subtract(1, 'day').endOf('day')

    return {
        backend: 'dagster',
        state: 'caught_up',
        freshThrough: freshThrough.toISOString(),
        lagSeconds: now.diff(freshThrough, 'second'),
        lastActivityAt: now.subtract(2, 'hour').toISOString(),
        initialBackfill: { complete: true, progressPct: 100 },
        totalRowsSynced: 8_900_000_000,
        error: null,
        updatedAt: now.toISOString(),
    }
}

export function formatRows(rows: number | null): string {
    if (rows == null) {
        return '—'
    }
    if (rows >= 1e9) {
        return `${(rows / 1e9).toFixed(1)}B`
    }
    if (rows >= 1e6) {
        return `${(rows / 1e6).toFixed(1)}M`
    }
    if (rows >= 1e3) {
        return `${(rows / 1e3).toFixed(1)}K`
    }
    return String(rows)
}

export function formatLag(seconds: number | null): string {
    if (seconds == null) {
        return 'unknown'
    }
    if (seconds < 60) {
        return `${Math.round(seconds)}s`
    }
    if (seconds < 3600) {
        return `${Math.round(seconds / 60)}m`
    }
    if (seconds < 86400) {
        return `${Math.round(seconds / 3600)}h`
    }
    const days = Math.round(seconds / 86400)
    return `${days}d`
}
