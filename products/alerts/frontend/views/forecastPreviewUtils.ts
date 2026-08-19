import { ForecastTargetDirection, InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { hasThresholdBounds } from 'products/alerts/frontend/logic/alertPreviewShared'

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

export function targetSummary(
    projection: { misses_on_forecast: boolean; misses_on_best_case: boolean },
    direction: ForecastTargetDirection | undefined
): string {
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
