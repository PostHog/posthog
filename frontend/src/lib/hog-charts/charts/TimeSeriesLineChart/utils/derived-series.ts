import { linearRegression } from 'simple-statistics'

import { movingAverage, trendLine } from 'lib/statistics'
import { hexToRGBA } from 'lib/utils'

import type { Series } from '../../../core/types'

const COMPARISON_DIM_OPACITY = 0.5
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

/** Filled band rendered behind the main series. The math (ciRanges) is the caller's
 *  responsibility — this helper only handles styling and the fill-between contract. */
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

/** Dashed overlay computed via the shared movingAverage helper. */
export function buildMovingAverageSeries<Meta = unknown>(input: BuildMovingAverageSeriesInput<Meta>): Series<Meta> {
    const { sourceSeries, window } = input
    return {
        key: `${sourceSeries.key}-ma`,
        label: input.label ?? `${sourceSeries.label} (Moving avg)`,
        data: movingAverage(sourceSeries.data, window),
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
 *  fitted in log-space and exp'd back, so it requires strictly-positive values; if any
 *  value is non-positive we fall back to linear rather than emitting NaNs. */
export function buildTrendLineSeries<Meta = unknown>(input: BuildTrendLineSeriesInput<Meta>): Series<Meta> {
    const { sourceSeries, kind, fitUpTo } = input
    const data =
        kind === 'exponential' ? exponentialTrend(sourceSeries.data, fitUpTo) : trendLine(sourceSeries.data, fitUpTo)
    const baseColor = sourceSeries.color
    return {
        key: `${sourceSeries.key}__trendline`,
        label: input.label ?? sourceSeries.label,
        data,
        color: baseColor ? hexToRGBA(baseColor, TREND_LINE_DIM_OPACITY) : undefined,
        yAxisId: sourceSeries.yAxisId,
        meta: sourceSeries.meta,
        stroke: { pattern: TREND_LINE_DASH_PATTERN },
        visibility: { fromTooltip: true, fromValueLabels: true, fromStack: true },
    }
}

function exponentialTrend(values: number[], fitUpTo?: number): number[] {
    const n = values.length
    if (n < 2 || values.some((v) => v <= 0)) {
        return trendLine(values, fitUpTo)
    }
    const fitEnd = fitUpTo != null ? Math.max(2, Math.min(fitUpTo, n)) : n
    const coords: [number, number][] = values.slice(0, fitEnd).map((y, x) => [x, Math.log(y)])
    const { m, b } = linearRegression(coords)
    return values.map((_, x) => Math.exp(m * x + b))
}

/** Re-render comparison series at reduced opacity so they read as subordinate to their
 *  primary. Series whose colour is missing or already an `rgba(...)` string are left as-is
 *  — `hexToRGBA` only handles hex inputs. */
export function applyComparisonDimming<Meta = unknown>(
    series: Series<Meta>[],
    comparisonOf: Record<string, string> | undefined
): Series<Meta>[] {
    if (!comparisonOf || Object.keys(comparisonOf).length === 0) {
        return series
    }
    return series.map((s) => {
        if (!(s.key in comparisonOf) || !s.color || !s.color.startsWith('#')) {
            return s
        }
        return { ...s, color: hexToRGBA(s.color, COMPARISON_DIM_OPACITY) }
    })
}
