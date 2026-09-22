import type { Series } from '@posthog/quill-charts'

import { findLastIndex } from 'lib/utils/arrays'

import type { ProcessedTimeseriesDataPoint } from '../../experimentTimeseriesLogic'

export const DELTA_SERIES_KEY = 'delta'
const PENDING_DASH_PATTERN = [5, 5]

export interface VariantTimeseriesSeries {
    series: Series[]
    lowerBounds: number[]
    upperBounds: number[]
}

export function buildVariantTimeseriesSeries(
    processedData: ProcessedTimeseriesDataPoint[],
    variantColor: string
): VariantTimeseriesSeries {
    // Days the daily job hasn't computed yet carry the last known value forward, so the line
    // stays continuous — dash the tail to show it isn't measured data. `fromIndex` dashes the
    // segment arriving at that point, so the first dashed segment leaves the last measured day.
    // With no measured day at all `fromIndex` is 0, which dashes the whole line.
    const lastRealIndex = findLastIndex(processedData, (point) => point.hasRealData)
    const firstPendingIndex = lastRealIndex + 1
    const hasPendingTail = firstPendingIndex < processedData.length

    return {
        series: [
            {
                key: DELTA_SERIES_KEY,
                label: 'Delta',
                data: processedData.map((point) => point.value ?? 0),
                color: variantColor,
                points: { radius: 3 },
                stroke: hasPendingTail
                    ? { partial: { fromIndex: firstPendingIndex, pattern: PENDING_DASH_PATTERN } }
                    : undefined,
            },
        ] satisfies Series[],
        lowerBounds: processedData.map((point) => point.lower_bound ?? 0),
        upperBounds: processedData.map((point) => point.upper_bound ?? 0),
    }
}
