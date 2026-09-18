export type UsageStats = {
    bytesReceived: number
    recordsReceived: number
    bytesAllowed: number
    recordsAllowed: number
    bytesDropped: number
    recordsDropped: number
}

export const DEFAULT_USAGE_STATS: UsageStats = {
    bytesReceived: 0,
    recordsReceived: 0,
    bytesAllowed: 0,
    recordsAllowed: 0,
    bytesDropped: 0,
    recordsDropped: 0,
}

export type UsageStatsByTeam = Map<number, UsageStats>

/**
 * Per-batch, per-team traffic tally. Steps record what they receive, allow
 * and drop; the afterBatch step turns the tally into Prometheus counters and
 * usage rows for billing.
 */
export class MetricsUsageAccumulator {
    private readonly stats: UsageStatsByTeam = new Map()

    recordReceived(teamId: number, bytes: number, records: number): void {
        const stats = this.statsFor(teamId)
        stats.bytesReceived += bytes
        stats.recordsReceived += records
    }

    recordAllowed(teamId: number, bytes: number, records: number): void {
        const stats = this.statsFor(teamId)
        stats.bytesAllowed += bytes
        stats.recordsAllowed += records
    }

    recordDropped(teamId: number, bytes: number, records: number): void {
        const stats = this.statsFor(teamId)
        stats.bytesDropped += bytes
        stats.recordsDropped += records
    }

    entries(): IterableIterator<[number, UsageStats]> {
        return this.stats.entries()
    }

    private statsFor(teamId: number): UsageStats {
        let stats = this.stats.get(teamId)
        if (!stats) {
            stats = { ...DEFAULT_USAGE_STATS }
            this.stats.set(teamId, stats)
        }
        return stats
    }
}

export interface MetricsUsageBatchContext {
    usage: MetricsUsageAccumulator
}
