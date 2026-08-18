import { ForecastTargetDirection, InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { hasThresholdBounds, valueBreachesBounds } from 'products/alerts/frontend/logic/alertPreviewShared'

/** Index into `forecastYhat` of the first point that crosses a threshold bound, or null if none does.
 *  The breach predicate itself comes from alertPreviewShared, which is kept in step with the
 *  backend comparator, so the forecast preview cannot drift from what actually fires. */
export function findFirstCrossing(forecastYhat: number[], bounds: InsightsThresholdBounds | null): number | null {
    if (!hasThresholdBounds(bounds)) {
        return null
    }
    for (let i = 0; i < forecastYhat.length; i++) {
        if (valueBreachesBounds(forecastYhat[i], bounds)) {
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
