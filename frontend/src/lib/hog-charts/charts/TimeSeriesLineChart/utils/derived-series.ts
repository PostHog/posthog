import { movingAverage } from 'lib/statistics'

import type { Series } from '../../../core/types'

const CI_FILL_OPACITY = 0.2
const MA_DASH_PATTERN = [10, 3]

export interface BuildConfidenceIntervalSeriesInput<Meta = unknown> {
    seriesKey: string
    label: string
    baseColor?: string
    lower: number[]
    upper: number[]
    yAxisId?: string
    meta?: Meta
    excluded?: boolean
}

export function buildConfidenceIntervalSeries<Meta = unknown>(
    input: BuildConfidenceIntervalSeriesInput<Meta>
): Series<Meta> {
    return {
        key: `${input.seriesKey}__ci`,
        label: `${input.label} (CI)`,
        data: input.upper,
        color: input.baseColor,
        yAxisId: input.yAxisId,
        meta: input.meta,
        fill: { opacity: CI_FILL_OPACITY, lowerData: input.lower },
        visibility: { excluded: input.excluded, fromTooltip: true, fromValueLabels: true },
    }
}

export interface BuildMovingAverageSeriesInput<Meta = unknown> {
    sourceSeries: Series<Meta>
    window: number
    label?: string
}

export function buildMovingAverageSeries<Meta = unknown>(input: BuildMovingAverageSeriesInput<Meta>): Series<Meta> {
    const { sourceSeries, window: windowSize } = input
    return {
        key: `${sourceSeries.key}-ma`,
        label: input.label ?? `${sourceSeries.label} (Moving avg)`,
        data: movingAverage(sourceSeries.data, windowSize),
        color: sourceSeries.color,
        yAxisId: sourceSeries.yAxisId,
        meta: sourceSeries.meta,
        stroke: { pattern: MA_DASH_PATTERN },
        visibility: { fromTooltip: true, fromStack: true },
    }
}
