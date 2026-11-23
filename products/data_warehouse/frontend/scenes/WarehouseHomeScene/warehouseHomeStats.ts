import type { DataHealthIssueApi, JobCountsApi, PipelineJobStatsResponseApi } from '../../generated/api.schemas'
import { formatCount } from '../WarehouseConsole/warehouseConsoleFormat'
import { statusBadge } from './warehouseHealthStatus'

export type JobStatsDays = 1 | 7 | 30

export interface RunBucket {
    /** The bucket start, as the API keys it: an ISO date, or an ISO hour for a one day window. */
    key: string
    successful: number
    failed: number
}

export interface PipelineTile {
    value: string
    detail: string
}

/** The share of runs that succeeded, as a whole percent. Null when nothing ran. */
export function successRatePercent(successful: number, total: number): number | null {
    return total > 0 ? Math.round((successful / total) * 100) : null
}

const pad = (value: number): string => String(value).padStart(2, '0')

/**
 * One bucket per day (or per hour for a one day window) of the window, with the days the API leaves out as zero.
 * The buckets follow the calendar of `cutoff_time` as the API writes it, so the project's timezone is kept.
 */
export function fillRunBuckets(stats: PipelineJobStatsResponseApi): RunBucket[] {
    const hourly = stats.days === 1
    const start = new Date(
        Date.UTC(
            Number(stats.cutoff_time.slice(0, 4)),
            Number(stats.cutoff_time.slice(5, 7)) - 1,
            Number(stats.cutoff_time.slice(8, 10)),
            hourly ? Number(stats.cutoff_time.slice(11, 13)) : 0
        )
    )
    // The window starts inside the first bucket, so one extra bucket is generated and the oldest is dropped.
    const count = (hourly ? 24 : stats.days) + 1
    const buckets: RunBucket[] = []
    for (let index = 0; index < count; index++) {
        const date = new Date(start.getTime() + index * (hourly ? 3_600_000 : 86_400_000))
        const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
        const key = hourly ? `${day}T${pad(date.getUTCHours())}` : day
        const matching = Object.entries(stats.breakdown).filter(([bucketKey]) => bucketKey.startsWith(key))
        buckets.push({
            key,
            successful: matching.reduce((sum, [, bucket]) => sum + bucket.successful, 0),
            failed: matching.reduce((sum, [, bucket]) => sum + bucket.failed, 0),
        })
    }
    return buckets.slice(1)
}

export function runSuccessTile(stats: PipelineJobStatsResponseApi): PipelineTile {
    const rate = successRatePercent(stats.successful_jobs, stats.total_jobs)
    return {
        value: rate === null ? 'No runs' : `${rate}%`,
        detail: `${formatCount(stats.successful_jobs)} of ${formatCount(stats.total_jobs)} runs`,
    }
}

/** Runs of one kind: the count in the window, then what failed or is running now. */
export function jobCountsTile(counts: JobCountsApi): PipelineTile {
    const parts = [
        counts.failed > 0 ? `${formatCount(counts.failed)} failed` : null,
        counts.running > 0 ? `${formatCount(counts.running)} running` : null,
    ].filter((part): part is string => part !== null)
    return {
        value: formatCount(counts.total),
        detail: parts.length > 0 ? parts.join(', ') : counts.total > 0 ? 'All succeeded' : 'No runs',
    }
}

export function needsAttentionTile(
    issues: DataHealthIssueApi[],
    countsByStatus: [string, number][]
): PipelineTile & { danger: boolean } {
    return {
        value: formatCount(issues.length),
        detail:
            issues.length === 0
                ? 'Nothing needs attention'
                : countsByStatus
                      .map(([status, count]) => `${count} ${statusBadge(status).label.toLowerCase()}`)
                      .join(', '),
        danger: issues.some((issue) => issue.status === 'failed'),
    }
}
