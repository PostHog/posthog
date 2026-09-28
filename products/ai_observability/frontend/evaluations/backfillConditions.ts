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

/** Raised, never replaced: a run whose units the live path graded mid-walk handles fewer than it
 * was created for, and those units are covered too. */
export function backfillTotalCount(backfill: EvaluationBackfillApi): number {
    return Math.max(backfill.total_count, backfill.dispatched_count + backfill.skipped_count)
}

export function backfillLateArrivalCount(backfill: EvaluationBackfillApi): number {
    return backfillTotalCount(backfill) - backfill.total_count
}

export function backfillCoveredCount(backfill: EvaluationBackfillApi): number {
    const total = backfillTotalCount(backfill)
    const covered =
        backfill.status === 'completed' && backfill.remaining_count !== null
            ? total - backfill.remaining_count
            : backfill.dispatched_count + backfill.skipped_count
    return clamp(covered, 0, total)
}
