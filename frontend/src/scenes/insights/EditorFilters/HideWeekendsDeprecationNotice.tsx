import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { TrendsQuery } from '~/queries/schema/schema-general'
import { isTrendsQuery } from '~/queries/utils'
import { BaseMathType, ChartDisplayType, InsightLogicProps } from '~/types'

export type HideWeekendsMigrationOutcome = 'switch' | 'remove' | 'keep'

/** Displays where the response has no per-day buckets, so hideWeekends never drops anything.
 * Mirrors TrendsDisplay.is_total_value in posthog/hogql_queries/insights/trends/display.py. */
const TOTAL_VALUE_DISPLAYS: ChartDisplayType[] = [
    ChartDisplayType.BoldNumber,
    ChartDisplayType.ActionsPie,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.WorldMap,
    ChartDisplayType.CalendarHeatmap,
    ChartDisplayType.ActionsTable,
]

/** What the hideWeekends deprecation migration will do to this query. Mirrors the migration
 * command's classification, which in turn mirrors the trends runner: hideWeekends only drops
 * day-interval buckets from time-series responses, and a rewrite to daysOfWeek is only
 * result-identical when no value aggregates across days (rolling math, cumulative, smoothing). */
/** Intervals the trends runner exempts from hideWeekends bucket dropping. "second" is absent
 * on purpose: the runner does drop buckets there, but daysOfWeek only drops day buckets, so a
 * second-interval query is a "keep", not a "remove". */
const EXEMPT_INTERVALS: string[] = ['minute', 'hour', 'week', 'month', 'quarter', 'year']

export function hideWeekendsMigrationOutcome(query: TrendsQuery): HideWeekendsMigrationOutcome {
    const interval = query.interval ?? 'day'
    const display = query.trendsFilter?.display ?? ChartDisplayType.ActionsLineGraph
    if (EXEMPT_INTERVALS.includes(interval) || TOTAL_VALUE_DISPLAYS.includes(display)) {
        return 'remove'
    }
    if (interval !== 'day') {
        return 'keep'
    }
    const hasWindowedMath = (query.series ?? []).some(
        (series) => series.math === BaseMathType.WeeklyActiveUsers || series.math === BaseMathType.MonthlyActiveUsers
    )
    if (
        hasWindowedMath ||
        display === ChartDisplayType.ActionsLineGraphCumulative ||
        (query.trendsFilter?.smoothingIntervals ?? 1) > 1 ||
        (query.dateRange?.daysOfWeek?.length ?? 0) > 0
    ) {
        return 'keep'
    }
    return 'switch'
}

const NOTICE_BY_OUTCOME: Record<HideWeekendsMigrationOutcome, string> = {
    switch: 'The "Hide weekend data" option is deprecated. This insight will soon switch to excluding weekends through the date filter\'s "Exclude" option instead. Its results won\'t change.',
    remove: 'The "Hide weekend data" option is deprecated. It has no effect on this insight, so it will soon be removed. Results won\'t change.',
    keep: 'The "Hide weekend data" option is deprecated but keeps working here. This insight can\'t switch to the date filter\'s "Exclude" option automatically, because weekend events still count toward its rolling or cumulative values.',
}

export function HideWeekendsDeprecationNotice({
    insightProps,
}: {
    insightProps: InsightLogicProps
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))

    if (
        !featureFlags[FEATURE_FLAGS.HIDE_WEEKENDS_DEPRECATION_NOTICE] ||
        !isTrendsQuery(querySource) ||
        !querySource.trendsFilter?.hideWeekends
    ) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey="hide-weekends-deprecation-notice" className="m-2">
            {NOTICE_BY_OUTCOME[hideWeekendsMigrationOutcome(querySource)]}
        </LemonBanner>
    )
}
