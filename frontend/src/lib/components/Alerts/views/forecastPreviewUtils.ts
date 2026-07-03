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
