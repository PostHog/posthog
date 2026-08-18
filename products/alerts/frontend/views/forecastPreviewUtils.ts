import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

/** Index into `forecastYhat` of the first point that crosses a threshold bound, or null if none does. */
export function findFirstCrossing(forecastYhat: number[], bounds: InsightsThresholdBounds | null): number | null {
    if (!bounds || (bounds.lower == null && bounds.upper == null)) {
        return null
    }
    for (let i = 0; i < forecastYhat.length; i++) {
        const value = forecastYhat[i]
        if ((bounds.upper != null && value > bounds.upper) || (bounds.lower != null && value < bounds.lower)) {
            return i
        }
    }
    return null
}

/** What the forecast says about a target, in one line. Both crossings are shown because the choice
 *  between the two sensitivities is easier to make by seeing the gap than by reading about it. */
export function targetSummary(projection: { misses_on_forecast: boolean; misses_on_best_case: boolean }): string {
    if (projection.misses_on_best_case) {
        return 'Falls short, and misses even in the best case'
    }
    if (projection.misses_on_forecast) {
        return 'Falls short on the current forecast'
    }
    return 'On track to reach the target'
}
