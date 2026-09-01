import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { DataModelingJob } from '~/types'

const LOGS_FILTER_FORMAT = 'YYYY-MM-DD HH:mm:ss'

function isParseableDate(value: string | null | undefined): value is string {
    return !!value && dayjs(value).isValid()
}

function latestOf(...values: (string | null | undefined)[]): string | null {
    const parseable = values.filter(isParseableDate)
    if (!parseable.length) {
        return null
    }
    return parseable.reduce((latest, value) => (dayjs(value).isAfter(dayjs(latest)) ? value : latest))
}

/** When the run ended, best-effort. Running jobs have no end yet. Failed and cancelled runs are
 * stamped by different write paths: a model save advances both fields, a bulk `QuerySet.update()`
 * skips the `auto_now` on `updated_at`, and rows predating the failure stamp still carry the run's
 * start time in `last_run_at`. Whichever is later is the end in all three cases. */
function jobEndTimestamp(job: DataModelingJob): string | null {
    if (job.status === 'Running') {
        return null
    }
    if (job.status === 'Completed') {
        return isParseableDate(job.last_run_at) ? job.last_run_at : null
    }
    return latestOf(job.updated_at, job.last_run_at)
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

/** When the data the view currently serves was synced. A run that failed, was cancelled, was
 * skipped, or was blocked by failing data quality checks leaves the previous version in place.
 * Only a completed run answers this. The newest run does not. */
export function latestSuccessfulSyncAt(jobs: DataModelingJob[] | undefined): string | null {
    return latestOf(...(jobs ?? []).filter((job) => job.status === 'Completed').map((job) => job.last_run_at))
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
