import { ForecastTargetDirection, InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { hasThresholdBounds } from 'products/alerts/frontend/logic/alertPreviewShared'

/** Index of the first predicted point that crosses a bound, mirroring _evaluate_future_breach_values
 *  in products/alerts/backend/evaluation/forecast.py.
 *
 *  `best_case` reads the edge that keeps the metric on the acceptable side: the LOWER edge against a
 *  ceiling and the UPPER edge against a floor, so it always fires later. Each bound is compared
 *  against its own series, which is why the shared valueBreachesBounds helper does not fit here: it
 *  checks both bounds against a single value. */
export function findFirstCrossing(
    series: { yhat: number[]; lower: number[]; upper: number[] },
    bounds: InsightsThresholdBounds | null,
    bestCase: boolean
): number | null {
    if (!hasThresholdBounds(bounds) || !bounds) {
        return null
    }
    const againstUpper = bestCase ? series.lower : series.yhat
    const againstLower = bestCase ? series.upper : series.yhat
    for (let i = 0; i < series.yhat.length; i++) {
        if (bounds.upper != null && againstUpper[i] > bounds.upper) {
            return i
        }
        if (bounds.lower != null && againstLower[i] < bounds.lower) {
            return i
        }
    }
    return null
}

/** What the forecast says about a target, in one line. Both crossings are shown because the choice
 *  between the two sensitivities is easier to make by seeing the gap than by reading about it. */
export function targetSummary(
    projection: { misses_on_forecast: boolean; misses_on_best_case: boolean },
    direction: ForecastTargetDirection | undefined
): string {
    // "Falls short" only reads correctly for a goal. For a budget the same miss is an overshoot.
    const miss = direction === ForecastTargetDirection.AT_MOST ? 'Goes over' : 'Falls short'
    if (projection.misses_on_best_case) {
        return `${miss}, and misses even in the best case`
    }
    if (projection.misses_on_forecast) {
        return `${miss} on the current forecast`
    }
    return direction === ForecastTargetDirection.AT_MOST
        ? 'On track to stay under the target'
        : 'On track to reach the target'
}
