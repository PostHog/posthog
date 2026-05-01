import React, { useMemo } from 'react'

import { LineChart } from '../charts/LineChart'
import type { ChartTheme, LineChartConfig, PointClickData, Series, TooltipContext } from '../core/types'

/** X-axis configuration. The labels array is the only stage-1 input the chart actually
 *  consumes — the rest is reserved for later stages so the public shape locks early. */
export interface TimeSeriesXAxis {
    /** Categorical labels — typically pre-formatted timestamps. Length must match each series.data. */
    labels: string[]
    /** Optional render-time formatter for each tick. Return null to skip a tick. */
    tickFormatter?: (value: string, index: number) => string | null
    /** Hide x-axis labels and reduce bottom margin. */
    hide?: boolean
}

/** Y-axis configuration. */
export interface TimeSeriesYAxis {
    /** `linear` (default) or `log`. Log clamps to a small positive epsilon to avoid log(0). */
    scale?: 'linear' | 'log'
    /** Optional formatter for y-axis tick labels. */
    tickFormatter?: (value: number) => string
    /** Hide y-axis labels and reduce left margin. */
    hide?: boolean
    /** Render horizontal grid lines at y-tick positions. */
    showGrid?: boolean
}

// TODO: stage 2 — render in-progress trailing segments (dashed tail, projected bucket).
export interface TimeSeriesInProgress {
    fromIndex?: number
}
// TODO: stage 3 — confidence-interval bands attached to a series by key.
export interface TimeSeriesConfidenceInterval {
    seriesKey: string
    upper: number[]
    lower: number[]
}
// TODO: stage 4 — moving-average overlay computed from the underlying series.
export interface TimeSeriesMovingAverage {
    seriesKey: string
    window: number
}
// TODO: stage 5 — least-squares trend lines for the listed series.
export interface TimeSeriesTrendLines {
    seriesKeys: string[]
}
// TODO: stage 6 — horizontal goal lines.
export interface TimeSeriesGoalLine {
    value: number
    label?: string
}
// TODO: stage 7 — colored threshold bands for upper/lower bounds.
export interface TimeSeriesThresholds {
    upper?: number
    lower?: number
}
// TODO: stage 8 — anomaly markers attached to specific (seriesKey, dataIndex) points.
export interface TimeSeriesAnomalies {
    points: { seriesKey: string; dataIndex: number; severity?: 'low' | 'medium' | 'high' }[]
}
// TODO: stage 9 — vertical annotations at specific x-axis labels.
export interface TimeSeriesAnnotation {
    label: string
    at: string
    color?: string
}
// TODO: stage 10 — value labels above each data point.
export interface TimeSeriesValueLabels {
    enabled?: boolean
    formatter?: (value: number) => string
}

export interface TimeSeriesLineChartProps<Meta = unknown> {
    /** Time-ordered series. Each `data` entry must align with `xAxis.labels` by index. */
    series: Series<Meta>[]
    /** X-axis configuration. */
    xAxis: TimeSeriesXAxis
    /** Y-axis configuration. Defaults to a linear primary axis. */
    yAxis?: TimeSeriesYAxis
    /** Theme colors. Build with `buildTheme()` so the wrapper itself stays PostHog-free. */
    theme: ChartTheme
    /** Wrapper width applied to the host container. */
    width?: number | string
    /** Wrapper height applied to the host container. */
    height?: number | string
    /** `data-attr` applied to the wrapper for product-level test selectors. */
    dataAttr?: string
    /** Class applied to the wrapper. */
    className?: string

    // The fields below intentionally lock the public shape early so future stages are
    // strictly additive. They are not consumed in stage 1 — passing them is a no-op.

    // TODO: stage 2
    inProgress?: TimeSeriesInProgress
    // TODO: stage 3
    confidenceIntervals?: TimeSeriesConfidenceInterval[]
    // TODO: stage 4
    movingAverage?: TimeSeriesMovingAverage
    // TODO: stage 5
    trendLines?: TimeSeriesTrendLines
    // TODO: stage 6
    goalLines?: TimeSeriesGoalLine[]
    // TODO: stage 7
    thresholds?: TimeSeriesThresholds
    // TODO: stage 8
    anomalies?: TimeSeriesAnomalies
    // TODO: stage 9
    annotations?: TimeSeriesAnnotation[]
    // TODO: stage 10
    valueLabels?: TimeSeriesValueLabels
    // TODO: stage 11
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    // TODO: stage 11
    onPointClick?: (data: PointClickData<Meta>) => void
}

const WRAPPER_BASE_STYLE: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
}

export function TimeSeriesLineChart<Meta = unknown>({
    series,
    xAxis,
    yAxis,
    theme,
    width = '100%',
    height = 280,
    dataAttr,
    className,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement {
    const config = useMemo<LineChartConfig>(
        () => ({
            yScaleType: yAxis?.scale,
            xTickFormatter: xAxis.tickFormatter,
            yTickFormatter: yAxis?.tickFormatter,
            hideXAxis: xAxis.hide,
            hideYAxis: yAxis?.hide,
            showGrid: yAxis?.showGrid,
        }),
        [xAxis.tickFormatter, xAxis.hide, yAxis?.scale, yAxis?.tickFormatter, yAxis?.hide, yAxis?.showGrid]
    )

    const wrapperStyle = useMemo<React.CSSProperties>(() => ({ ...WRAPPER_BASE_STYLE, width, height }), [width, height])

    return (
        <div
            data-attr={dataAttr}
            className={className}
            // eslint-disable-next-line react/forbid-dom-props
            style={wrapperStyle}
        >
            <LineChart series={series} labels={xAxis.labels} config={config} theme={theme} />
        </div>
    )
}
