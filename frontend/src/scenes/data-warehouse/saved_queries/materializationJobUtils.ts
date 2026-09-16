import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { DataModelingJob } from '~/types'

const LOGS_FILTER_FORMAT = 'YYYY-MM-DD HH:mm:ss'

/** The fields the duration helpers read. Both the handwritten job type and the generated `DataModelingJobApi` satisfy it. */
type JobTiming = Pick<DataModelingJob, 'created_at' | 'updated_at' | 'last_run_at'> & { status: string }

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
function jobEndTimestamp(job: JobTiming): string | null {
    if (job.status === 'Running') {
        return null
    }
    if (job.status === 'Completed') {
        return isParseableDate(job.last_run_at) ? job.last_run_at : null
    }
    return latestOf(job.updated_at, job.last_run_at)
}

export function computeJobDuration(job: JobTiming): string {
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
export function latestSuccessfulSyncAt(jobs: JobTiming[] | undefined): string | null {
    return latestOf(...(jobs ?? []).filter((job) => job.status === 'Completed').map((job) => job.last_run_at))
}

/** Time window for the run's log search. An open `dateTo` (still running, or no usable end
 * timestamp) lets the LogsViewer default to "now" instead of silently cutting off logs. */
export function jobLogsWindow(job: JobTiming, timezone: string): { dateFrom?: string; dateTo?: string } {
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

interface FullRefreshReasonCopy {
    label: string
    explanation: string
}

/** Short label and explanation for a run that rebuilt the whole table, keyed by the reason the
 * backend stored on the job. An unrecognized reason is shown as stored, so a reason added later
 * still says something.
 *
 * Each explanation describes only the run it belongs to. The backend stamps the reason when it
 * plans the run, so the same copy also has to hold for a run that is still going, for one that
 * failed without recording a watermark, and for one that ran before the view's current settings. */
const FULL_REFRESH_REASONS: Record<string, FullRefreshReasonCopy> = {
    'first run': {
        label: 'First run',
        explanation: 'This was the first run, so there were no rows to add to.',
    },
    'definition changed': {
        label: 'Definition changed',
        explanation: 'The query or the incremental keys changed, so the stored rows no longer matched them.',
    },
    'no usable watermark': {
        label: 'No watermark',
        explanation:
            'The last run recorded no value for the incremental key, so there was no point to continue from. Check that the incremental key has values in the query output.',
    },
    'table missing': {
        label: 'Table missing',
        explanation: 'There was no table to add rows to, so this run built it again.',
    },
    'not configured for incremental materialization': {
        label: 'Not configured',
        explanation: 'Incremental updates were off for this view when this run started.',
    },
    'incremental materialization is not enabled': {
        label: 'Not available',
        explanation: 'Incremental updates were not available for this project when this run started.',
    },
}

export function fullRefreshReasonCopy(reason: string | null | undefined): FullRefreshReasonCopy | null {
    if (!reason) {
        return null
    }
    return FULL_REFRESH_REASONS[reason] ?? { label: reason, explanation: reason }
}
