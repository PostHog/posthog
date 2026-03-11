import type React from 'react'

import type { AxisFormat, ChartTheme } from 'lib/charts/types'

export type LineStyle = 'solid' | 'dashed' | 'dotted'

export interface Series {
    label: string
    data: number[]
    pointLabels?: string[]
    color?: string
    hidden?: boolean
    /** Opaque metadata passed through to tooltips and click events — never read by HogCharts. */
    meta?: Record<string, unknown>
    yAxisPosition?: 'left' | 'right'
    trendLine?: boolean
    fill?: boolean
    lineStyle?: LineStyle
    /** Rendered but excluded from tooltips (for CI bounds, moving averages, etc.). */
    hideFromTooltip?: boolean
}

export interface ComparisonSeries extends Series {
    compareLabel: string
}

export type ChartInterval = 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month'

export type { AxisFormat } from 'lib/charts/types'

export type AxisScale = 'linear' | 'logarithmic'

export interface AxisConfig {
    label?: string
    format?: AxisFormat
    prefix?: string
    suffix?: string
    decimalPlaces?: number
    scale?: AxisScale
    startAtZero?: boolean
    gridLines?: boolean
    min?: number
    max?: number
}

export interface GoalLine {
    value: number
    label?: string
    color?: string
    style?: LineStyle
}

export interface Annotation {
    at: string
    label: string
    description?: string
    color?: string
}

export type LegendPosition = 'top' | 'bottom' | 'left' | 'right' | 'none'

export interface LegendConfig {
    position?: LegendPosition
    maxItems?: number
}

export interface TooltipPoint {
    seriesIndex: number
    pointIndex: number
    value: number
    seriesLabel: string
    color: string
    meta?: Record<string, unknown>
}

export interface TooltipContext {
    label: string
    points: TooltipPoint[]
    position: { x: number; y: number }
    chartBounds: DOMRect
}

export interface TooltipConfig {
    shared?: boolean
    formatValue?: (value: number, seriesIndex: number) => string
    render?: (context: TooltipContext) => React.ReactNode
    onHide?: () => void
}

export interface HogChartTheme extends ChartTheme {
    fontFamily?: string
    fontSize?: number
    backgroundColor?: string
    goalLineColor?: string
    tooltipBorderRadius?: number
}

export interface BaseChartProps {
    width?: number | string
    height?: number | string
    theme?: Partial<HogChartTheme>
    legend?: LegendConfig
    tooltip?: TooltipConfig
    className?: string
    animate?: boolean
    ariaLabel?: string
    onClick?: (point: ClickEvent) => void
}

export interface ClickEvent {
    seriesIndex: number
    pointIndex: number
    value: number
    label: string
    seriesLabel: string
    meta?: Record<string, unknown>
}

export interface TimeSeriesProps extends BaseChartProps {
    data: Series[]
    compare?: ComparisonSeries[]
    labels: string[]
    xAxis?: AxisConfig
    /** Single config or `[left, right]` tuple for dual y-axes. */
    yAxis?: AxisConfig | [AxisConfig, AxisConfig]
    goalLines?: GoalLine[]
    annotations?: Annotation[]
    showValues?: boolean
    showTrendLine?: boolean

    /** Raw date strings from the query — enables smart x-axis tick formatting. */
    dates?: (string | number)[]
    interval?: ChartInterval
    timezone?: string
    xAxisTickCallback?: (value: string | number, index: number) => string | null
}

export type LineInterpolation = 'linear' | 'smooth' | 'step'

export interface LineProps extends TimeSeriesProps {
    cumulative?: boolean
    interpolation?: LineInterpolation
    showDots?: boolean | 'auto'
    lineWidth?: number
    stacked?: boolean
    percentStacked?: boolean
    isArea?: boolean
    fillOpacity?: number
    hideXAxis?: boolean
    hideYAxis?: boolean
    crosshair?: boolean
    /** Trailing data points rendered as dotted (in-progress time period). */
    incompletePoints?: number
    highlightSeriesIndex?: number | null
    onHighlightChange?: (seriesIndex: number | null) => void
    maxSeries?: number
}

export type AreaProps = LineProps
