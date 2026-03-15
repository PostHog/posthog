import type React from 'react'

import type { AxisFormat, ChartTheme } from 'lib/charts/types'

export type LineStyle = 'solid' | 'dashed' | 'dotted'

export interface DataPoint {
    x: string | number
    y: number
    status?: 'incomplete'
}

export interface Series {
    label: string
    data: DataPoint[]
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
    series: Series[]
    compare?: ComparisonSeries[]
    xAxis?: AxisConfig
    /** Single config or `[left, right]` tuple for dual y-axes. */
    yAxis?: AxisConfig | [AxisConfig, AxisConfig]
    goalLines?: GoalLine[]
    annotations?: Annotation[]
    interval?: ChartInterval
}

export type LineInterpolation = 'linear' | 'smooth' | 'step'

export interface LineOptions {
    stacked?: boolean
    percentStacked?: boolean
    isArea?: boolean
    fillOpacity?: number
    cumulative?: boolean
    interpolation?: LineInterpolation
    showDots?: boolean | 'auto'
    lineWidth?: number
    crosshair?: boolean
    hideXAxis?: boolean
    hideYAxis?: boolean
    maxSeries?: number
    showValues?: boolean
    showTrendLine?: boolean
    animate?: boolean
}

export interface LineProps extends TimeSeriesProps {
    options?: LineOptions
    highlightSeriesIndex?: number | null
    onHighlightChange?: (seriesIndex: number | null) => void
}

export type AreaProps = LineProps
