import type React from 'react'

export interface Series {
    label: string
    data: number[]
    pointLabels?: string[]
    color?: string
    hidden?: boolean
    /** Opaque metadata passed through to tooltips and click events — never read by HogCharts. */
    meta?: Record<string, unknown>
    displayType?: 'line' | 'bar'
    yAxisPosition?: 'left' | 'right'
    trendLine?: boolean
    fill?: boolean
    lineStyle?: 'solid' | 'dashed' | 'dotted'
    /** Rendered but excluded from tooltips (for CI bounds, moving averages, etc.). */
    hideFromTooltip?: boolean
}

export interface ComparisonSeries extends Series {
    compareLabel: string
}

export type ChartInterval = 'second' | 'minute' | 'hour' | 'day' | 'week' | 'month'

export type AxisFormat =
    | 'number'
    | 'compact'
    | 'percent'
    | 'duration'
    | 'duration_ms'
    | 'date'
    | 'datetime'
    | 'none'

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
    style?: 'solid' | 'dashed' | 'dotted'
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

export interface HogChartTheme {
    colors: string[]
    fontFamily?: string
    fontSize?: number
    backgroundColor?: string
    axisColor?: string
    gridColor?: string
    goalLineColor?: string
    tooltipBackground?: string
    tooltipColor?: string
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

export type LineStyle = 'solid' | 'dashed' | 'dotted'
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

export type BarOrientation = 'vertical' | 'horizontal'

export interface BarProps extends TimeSeriesProps {
    stacked?: boolean
    percentStacked?: boolean
    orientation?: BarOrientation
    borderRadius?: number
    barGap?: number
}

export interface PieSlice {
    label: string
    value: number
    color?: string
    meta?: Record<string, unknown>
}

export interface PieProps extends BaseChartProps {
    data: PieSlice[]
    donut?: boolean
    innerRadius?: number
    showLabels?: boolean
    showValues?: boolean
}

export interface NumberProps extends BaseChartProps {
    value: number
    previousValue?: number
    label?: string
    format?: AxisFormat
    prefix?: string
    suffix?: string
}

export interface FunnelStep {
    label: string
    count: number
    breakdown?: { label: string; count: number }[]
    /** Seconds from previous step. */
    medianTime?: number
}

export type FunnelLayout = 'horizontal' | 'vertical'
export type FunnelVizType = 'steps' | 'time_to_convert' | 'trends'

export interface FunnelProps extends BaseChartProps {
    steps: FunnelStep[]
    layout?: FunnelLayout
    vizType?: FunnelVizType
    showConversionRates?: boolean
    showTime?: boolean
    goalLines?: GoalLine[]
}

export interface RetentionCohort {
    label: string
    date: string
    /** Index 0 is cohort size, rest are retention counts. */
    values: number[]
}

export type RetentionPeriod = 'hour' | 'day' | 'week' | 'month'

export interface RetentionProps extends BaseChartProps {
    data: RetentionCohort[]
    periodLabels: string[]
    period?: RetentionPeriod
    showPercentages?: boolean
    showCounts?: boolean
}

export interface PathNode {
    name: string
    count: number
}

export interface PathLink {
    source: string
    target: string
    value: number
    /** Seconds between source and target. */
    averageTime?: number
}

export interface PathsProps extends BaseChartProps {
    nodes: PathNode[]
    links: PathLink[]
    maxPaths?: number
    highlightPath?: string[]
}

export interface MapDataPoint {
    /** ISO 3166-1 alpha-2. */
    code: string
    value: number
    label?: string
}

export interface WorldMapProps extends BaseChartProps {
    data: MapDataPoint[]
    colorRange?: [string, string]
    showLabels?: boolean
}

export interface BoxPlotDatum {
    label: string
    min: number
    q1: number
    median: number
    q3: number
    max: number
    mean?: number
    outliers?: number[]
}

export interface BoxPlotProps extends BaseChartProps {
    data: BoxPlotDatum[]
    xAxis?: AxisConfig
    yAxis?: AxisConfig
    showMean?: boolean
    showOutliers?: boolean
}

export interface HeatmapCell {
    x: string | number
    y: string | number
    value: number
}

export interface HeatmapProps extends BaseChartProps {
    data: HeatmapCell[]
    xLabels: string[]
    yLabels: string[]
    xAxis?: AxisConfig
    yAxis?: AxisConfig
    colorRange?: string[]
    showValues?: boolean
    borderRadius?: number
}

export type LifecycleStatus = 'new' | 'returning' | 'resurrecting' | 'dormant'

export interface LifecycleBucket {
    label: string
    new: number
    returning: number
    resurrecting: number
    dormant: number
}

export interface LifecycleProps extends BaseChartProps {
    data: LifecycleBucket[]
    labels: string[]
    xAxis?: AxisConfig
    yAxis?: AxisConfig
    goalLines?: GoalLine[]
    statusColors?: Partial<Record<LifecycleStatus, string>>
    visibleStatuses?: LifecycleStatus[]
    showValues?: boolean
}

export type StickinessProps = TimeSeriesProps

export type HogChartProps =
    | ({ type: 'line' } & LineProps)
    | ({ type: 'bar' } & BarProps)
    | ({ type: 'area' } & AreaProps)
    | ({ type: 'pie' } & PieProps)
    | ({ type: 'number' } & NumberProps)
    | ({ type: 'funnel' } & FunnelProps)
    | ({ type: 'retention' } & RetentionProps)
    | ({ type: 'paths' } & PathsProps)
    | ({ type: 'worldmap' } & WorldMapProps)
    | ({ type: 'boxplot' } & BoxPlotProps)
    | ({ type: 'heatmap' } & HeatmapProps)
    | ({ type: 'lifecycle' } & LifecycleProps)
    | ({ type: 'stickiness' } & StickinessProps)
