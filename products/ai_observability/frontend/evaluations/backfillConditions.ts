import { dayjs } from 'lib/dayjs'
import { clamp } from 'lib/utils/numbers'

import type { EvaluationBackfillApi, EvaluationBackfillConditionApi } from '../generated/api.schemas'

export function backfillSamplingLabel(condition: EvaluationBackfillConditionApi): string {
    const percent = condition.rollout_percentage ?? 100
    // A rollout under 1% is still a real sample, so one decimal is not enough to tell 0.04 from 0.
    const decimals = percent < 1 ? 2 : percent < 100 ? 1 : 0
    const factor = 10 ** decimals
    // A partial sample that rounds up to 100 would read as "every unit", so hold it below.
    const shown = percent < 100 ? Math.min(Math.round(percent * factor), 100 * factor - 1) / factor : percent
    return `${parseFloat(shown.toFixed(decimals))}% sampled`
}

/** The year is noise while a range sits inside the current year, and load-bearing as soon as
 * either bound leaves it. Both bounds share one format so the range reads as one span. */
export function backfillRangeDateFormat(start: string, end: string, now: dayjs.Dayjs): string {
    const sameYear = dayjs(start).isSame(now, 'year') && dayjs(end).isSame(now, 'year')
    return sameYear ? 'MMM D' : 'MMM D, YYYY'
}

export function backfillCoveredCount(backfill: EvaluationBackfillApi): number {
    // A finished run knows what the window still owed. Until then, coverage is what the walk itself
    // handled. The total is the estimate taken at creation while the remainder is counted later, so
    // an event arriving in between can leave more owed than the total ever held.
    const covered =
        backfill.status === 'completed' && backfill.remaining_count !== null
            ? backfill.total_count - backfill.remaining_count
            : backfill.dispatched_count + backfill.skipped_count
    return clamp(covered, 0, backfill.total_count)
}
