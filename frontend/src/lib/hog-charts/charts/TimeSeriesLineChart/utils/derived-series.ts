import { linearRegression, movingAverage, trendLine } from 'lib/statistics'

import type { Series } from '../../../core/types'
import { dimHex } from '../../../utils/comparison-dimming'

const TREND_LINE_DIM_OPACITY = 0.5
const CI_FILL_OPACITY = 0.2
const MA_DASH_PATTERN = [10, 3]
const TREND_LINE_DASH_PATTERN = [1, 3]

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

export function movingAverageKey(sourceKey: string): string {
    return `${sourceKey}-ma`
}

export function buildMovingAverageSeries<Meta = unknown>(input: BuildMovingAverageSeriesInput<Meta>): Series<Meta> {
    const { sourceSeries, window: windowSize } = input
    return {
        key: movingAverageKey(sourceSeries.key),
        label: input.label ?? `${sourceSeries.label} (Moving avg)`,
        data: movingAverage(sourceSeries.data, windowSize),
        color: sourceSeries.color,
        yAxisId: sourceSeries.yAxisId,
        meta: sourceSeries.meta,
        stroke: { pattern: MA_DASH_PATTERN },
        visibility: { fromTooltip: true, fromStack: true },
    }
}

export interface BuildTrendLineSeriesInput<Meta = unknown> {
    sourceSeries: Series<Meta>
    kind: 'linear' | 'exponential'
    label?: string
    /** When set, only the prefix `[0, fitUpTo)` contributes to the regression, but the
     *  trend is extrapolated across the full data range. Useful for excluding an
     *  in-progress tail so the partial bucket doesn't drag the slope. */
    fitUpTo?: number
}

/** Linear or exponential regression rendered as a dimmed dotted line. Exponential is
 *  fitted in log-space and exp'd back, so it falls back to linear when any value in the
 *  fit range is non-positive (log-space is undefined there). Colour dimming is applied
 *  only to hex source colours; non-hex inputs are passed through untouched (mirrors
 *  `applyComparisonDimming`). */
export function buildTrendLineSeries<Meta = unknown>(input: BuildTrendLineSeriesInput<Meta>): Series<Meta> {
    const { sourceSeries, kind, fitUpTo } = input
    const data =
        kind === 'exponential' ? exponentialTrend(sourceSeries.data, fitUpTo) : trendLine(sourceSeries.data, fitUpTo)
    const baseColor = sourceSeries.color
    return {
        key: `${sourceSeries.key}__trendline`,
        label: input.label ?? sourceSeries.label,
        data,
        color: dimHex(baseColor, TREND_LINE_DIM_OPACITY),
        yAxisId: sourceSeries.yAxisId,
        meta: sourceSeries.meta,
        stroke: { pattern: TREND_LINE_DASH_PATTERN },
        visibility: { fromTooltip: true, fromValueLabels: true, fromStack: true },
    }
}

function exponentialTrend(values: number[], fitUpTo?: number): number[] {
    const n = values.length
    if (n < 2) {
        return trendLine(values, fitUpTo)
    }
    const fitEnd = fitUpTo != null ? Math.max(2, Math.min(fitUpTo, n)) : n
    // Single pass: build the log-space coords and bail on the first non-positive value.
    // The prefix `[0, fitEnd)` is the only region that contributes to the regression,
    // so a 0 in the in-progress tail mustn't force a fallback.
    const coords: [number, number][] = []
    for (let x = 0; x < fitEnd; x++) {
        const y = values[x]
        if (y <= 0) {
            return trendLine(values, fitUpTo)
        }
        coords.push([x, Math.log(y)])
    }
    const { m, b } = linearRegression(coords)
    return values.map((_, x) => Math.exp(m * x + b))
}
