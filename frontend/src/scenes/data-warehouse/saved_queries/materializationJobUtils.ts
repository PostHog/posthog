import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import type { IncrementalConfigDraft } from 'scenes/data-warehouse/editor/IncrementalConfigFields'

import { DataModelingJob, DataWarehouseSavedQueryIncremental, LogEntryLevel } from '~/types'

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

export const MATERIALIZATION_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARN', 'WARNING', 'ERROR']

// Watermarks are only ISO strings for date/datetime incremental keys. Numeric and arbitrary
// string keys must render as-is: pushing them through a date formatter shows a bogus timestamp.
const ISO_DATE_PREFIX = /^\d{4}-\d{2}-\d{2}([T ]|$)/

export function formatWatermark(watermark: string | null | undefined): string {
    if (watermark == null || watermark === '') {
        return 'the last run'
    }
    return ISO_DATE_PREFIX.test(watermark) ? humanFriendlyDetailedTime(watermark) : watermark
}

export function getMaterializationStatusMessage(
    rowsMaterialized: number,
    progressPercentage: number,
    rowsExpected: number
): string {
    const percentComplete = Math.round(Math.min(100, (rowsMaterialized / rowsExpected) * 100))
    switch (true) {
        case rowsMaterialized === 0:
            return `Spinning up spikes — starting materialization job... ${percentComplete}% complete.`
        case progressPercentage < 10:
            return `Digging into SQL... executing your query now... ${percentComplete}% complete.`
        case progressPercentage < 25:
            return `First ${humanFriendlyNumber(rowsMaterialized)} rows tucked away... ${percentComplete}% complete.`
        case progressPercentage < 50:
            return `${humanFriendlyNumber(rowsMaterialized)} rows shipped to storage... ${percentComplete}% complete.`
        case progressPercentage < 90:
            return `Still going — ${humanFriendlyNumber(
                rowsMaterialized
            )} rows written... ${percentComplete}% complete.`
        case progressPercentage === 100:
            return `Wrapping up — ${humanFriendlyNumber(
                rowsMaterialized
            )} rows processed... ${percentComplete}% complete.`
        default:
            return `Almost there — ${humanFriendlyNumber(
                rowsMaterialized
            )} rows processed... ${percentComplete}% complete.`
    }
}

export function refreshModeChange(
    savedIncremental: DataWarehouseSavedQueryIncremental | null | undefined,
    incrementalDraft: IncrementalConfigDraft
): { structuralChange: boolean; refreshModeChanged: boolean } {
    // Key or unique-key edits change what the stored rows mean, so the next run rebuilds (via the
    // definition fingerprint). A lookback-only change is operational and does not.
    const structuralChange = savedIncremental?.enabled
        ? !incrementalDraft.enabled ||
          incrementalDraft.incrementalKey !== savedIncremental.incremental_key ||
          [...incrementalDraft.uniqueKey].sort().join(',') !== [...savedIncremental.unique_key].sort().join(',')
        : incrementalDraft.enabled
    const lookbackChanged =
        !!savedIncremental?.enabled &&
        incrementalDraft.enabled &&
        incrementalDraft.lookbackSeconds !== (savedIncremental.lookback_seconds ?? 0)
    return { structuralChange, refreshModeChanged: structuralChange || lookbackChanged }
}
