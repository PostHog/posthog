import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

/** Whether a threshold has at least one bound set. Shared by the funnel and SQL configure-time
 * previews so their breach logic can't drift. */
export function hasThresholdBounds(bounds: InsightsThresholdBounds | null | undefined): boolean {
    return !!bounds && (bounds.lower != null || bounds.upper != null)
}

/** Whether a value breaches the absolute bounds right now — mirrors the backend comparator's strict
 * `< lower` / `> upper` (products/alerts/backend/evaluation/comparator.py). A null value never breaches.
 * Single source of truth for both alert previews; keep it in sync with the comparator. */
export function valueBreachesBounds(value: number | null, bounds: InsightsThresholdBounds | null | undefined): boolean {
    if (value === null) {
        return false
    }
    return (bounds?.lower != null && value < bounds.lower) || (bounds?.upper != null && value > bounds.upper)
}
