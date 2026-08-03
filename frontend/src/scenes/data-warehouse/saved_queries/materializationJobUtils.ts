import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { DataModelingJob } from '~/types'

const LOGS_FILTER_FORMAT = 'YYYY-MM-DD HH:mm:ss'

/** When the run ended, best-effort. Failed and cancelled runs historically never advanced
 * `last_run_at` past the job's start, so `updated_at` (stamped on the terminal save) is the
 * more reliable end marker for them. Running jobs have no end yet. */
function jobEndTimestamp(job: DataModelingJob): string | null {
    if (job.status === 'Running') {
        return null
    }
    if (job.status === 'Completed') {
        return job.last_run_at ?? null
    }
    return job.updated_at ?? job.last_run_at ?? null
}

function isParseableDate(value: string | null | undefined): value is string {
    return !!value && dayjs(value).isValid()
}

export function computeJobDuration(job: DataModelingJob): string {
    if (job.status === 'Running') {
        return 'In progress'
    }
    const end = jobEndTimestamp(job)
    if (!isParseableDate(job.created_at) || !isParseableDate(end)) {
        return '-'
    }
    const durationSeconds = (new Date(end).getTime() - new Date(job.created_at).getTime()) / 1000
    if (durationSeconds <= 0) {
        return '-'
    }
    return humanFriendlyDuration(durationSeconds)
}

/** Time window for the run's log search. An open `dateTo` (still running, or no usable end
 * timestamp) lets the LogsViewer default to "now" instead of silently cutting off logs. */
export function jobLogsWindow(job: DataModelingJob, timezone: string): { dateFrom?: string; dateTo?: string } {
    const end = jobEndTimestamp(job)
    return {
        dateFrom: isParseableDate(job.created_at)
            ? dayjsUtcToTimezone(job.created_at, timezone).format(LOGS_FILTER_FORMAT)
            : undefined,
        dateTo: isParseableDate(end)
            ? dayjsUtcToTimezone(end, timezone).add(1, 'hour').format(LOGS_FILTER_FORMAT)
            : undefined,
    }
}
