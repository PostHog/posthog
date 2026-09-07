import { dayjs } from 'lib/dayjs'

import type { AnyPropertyFilter } from '~/types'

import type { EvaluationBackfillConditionApi } from '../generated/api.schemas'

/** The generated type carries property filters as plain dicts, while the display components take
 * the filter union. The two agree at runtime, mirroring the cast in `toRequestConditions`. */
export function backfillConditionFilters(condition: EvaluationBackfillConditionApi): AnyPropertyFilter[] {
    return (condition.properties ?? []) as AnyPropertyFilter[]
}

export function backfillSamplingPercent(condition: EvaluationBackfillConditionApi): number {
    return condition.rollout_percentage ?? 100
}

export function backfillSamplingLabel(condition: EvaluationBackfillConditionApi): string {
    const percent = backfillSamplingPercent(condition)
    // A rollout under 1% is still a real sample, so one decimal is not enough to tell 0.04 from 0.
    const decimals = percent < 1 ? 2 : percent < 100 ? 1 : 0
    return `${parseFloat(percent.toFixed(decimals))}% sampled`
}

/** The year is noise while a range sits inside the current year, and load-bearing as soon as
 * either bound leaves it. Both bounds share one format so the range reads as one span. */
export function backfillRangeDateFormat(start: string, end: string, now: dayjs.Dayjs): string {
    const sameYear = dayjs(start).isSame(now, 'year') && dayjs(end).isSame(now, 'year')
    return sameYear ? 'MMM D' : 'MMM D, YYYY'
}
