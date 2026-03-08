/**
 * HogCharts — Core type definitions.
 *
 * These types form the public API surface. They are designed to be:
 * - Self-documenting (no magic strings where enums/unions suffice)
 * - Progressively disclosed (simple cases need few fields)
 * - Impossible to misuse (chart-specific data has chart-specific types)
 */

import type React from 'react'

// ---------------------------------------------------------------------------
// Universal primitives
// ---------------------------------------------------------------------------

/** A single data series for time-series and categorical charts. */
export interface Series {
    /** Human-readable name shown in legends and tooltips. */
    label: string
    /** Ordered numeric values — one per label on the x-axis. */
    data: number[]
    /** Optional per-point labels (overrides shared `labels`). */
    pointLabels?: string[]
    /** Hex color, CSS var, or preset token (e.g. `"preset-1"`). */
    color?: string
    /**
     * When `true`, the series is rendered but hidden by default
     * (user can toggle it via the legend).
     */
    hidden?: boolean
    /**
     * Opaque metadata bag passed through to tooltip context and click events.
     * HogCharts never reads this — it's for consumers to attach domain-specific
     * data (e.g. action definitions, breakdown values, person URLs).
     */
    meta?: Record<string, unknown>

    // -- Per-series overrides (for mixed charts and advanced config) ----------

    /**
     * Override the display type for this individual series.
     * Enables mixed charts (e.g. some series as lines, others as bars).
     * When omitted, inherits from the chart component used.
     */
    displayType?: 'line' | 'bar'
    /** Which y-axis this series belongs to. Defaults to `"left"`. */
    yAxisPosition?: 'left' | 'right'
    /** Show a trend line for this specific series. */
    trendLine?: boolean
    /** Fill area under this series. When on a Line chart, creates a mixed line+area. */
    fill?: boolean
    /** Custom border dash pattern (e.g. `[6, 4]` for dashed). */
    borderDash?: number[]
    /** Override border width for this series. */
    borderWidth?: number
    /** Override point radius for this series. */
    pointRadius?: number
    /**
     * When `true`, this series is rendered but excluded from tooltips.
     * Useful for CI bounds, moving averages, and other auxiliary series.
     */
    hideFromTooltip?: boolean
}

/** A comparison series displayed alongside the primary data. */
export interface ComparisonSeries extends Series {
    /** How the comparison relates to the primary (e.g. "previous period"). */
    compareLabel: string
}

// ---------------------------------------------------------------------------
// Axis configuration
// ---------------------------------------------------------------------------

/** Time interval granularity for time-series charts. */
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
    /** Axis label text. */
    label?: string
    /** How values are formatted on ticks and in tooltips. */
    format?: AxisFormat
    /** Numeric prefix (e.g. `"$"`). */
    prefix?: string
    /** Numeric suffix (e.g. `"%"`). */
    suffix?: string
    /** Number of decimal places. */
    decimalPlaces?: number
    /** Scale type — defaults to `"linear"`. */
    scale?: AxisScale
    /** Force the axis to start at zero. Defaults to `true` for bar charts. */
    startAtZero?: boolean
    /** Show grid lines. Defaults to `true` for y-axes, `false` for x-axes. */
    gridLines?: boolean
    /** Min/max bounds. */
    min?: number
    max?: number
}

// ---------------------------------------------------------------------------
// Decorations
// ---------------------------------------------------------------------------

export interface GoalLine {
    /** The y-value where the line is drawn. */
    value: number
    /** Optional label displayed alongside the line. */
    label?: string
    /** Line color — defaults to the theme's goal-line color. */
    color?: string
    /** Line style. Defaults to `"dashed"`. */
    style?: 'solid' | 'dashed' | 'dotted'
}

export interface Annotation {
    /** The x-axis label or date string where the annotation appears. */
    at: string
    /** Short text label. */
    label: string
    /** Optional longer description shown on hover. */
    description?: string
    /** Marker color. */
    color?: string
}

// ---------------------------------------------------------------------------
// Legend & tooltip
// ---------------------------------------------------------------------------

export type LegendPosition = 'top' | 'bottom' | 'left' | 'right' | 'none'

export interface LegendConfig {
    position?: LegendPosition
    /** Maximum number of items before scrolling. */
    maxItems?: number
}

/** A single data point in the tooltip context. */
export interface TooltipPoint {
    /** Index of the series in the `data` array. */
    seriesIndex: number
    /** Index of the data point within the series. */
    pointIndex: number
    /** The raw numeric value. */
    value: number
    /** The series label. */
    seriesLabel: string
    /** Resolved hex color for this series. */
    color: string
    /** The `meta` bag from the series, if provided. */
    meta?: Record<string, unknown>
}

/** Context passed to custom tooltip render functions. */
export interface TooltipContext {
    /** The x-axis label at the hovered position. */
    label: string
    /** All data points at this x position (or the single hovered point). */
    points: TooltipPoint[]
    /** Canvas-relative coordinates of the hover position. */
    position: { x: number; y: number }
    /** Bounding rect of the chart container element. */
    chartBounds: DOMRect
}

export interface TooltipConfig {
    /**
     * Show a shared tooltip for all series at the hovered x position.
     * When `false`, only the nearest single point is shown. Defaults to `true`.
     */
    shared?: boolean
    /** Custom value formatter for the built-in tooltip. */
    formatValue?: (value: number, seriesIndex: number) => string
    /**
     * Custom render function — replaces the built-in tooltip entirely.
     * Return a React element that will be portalled next to the chart.
     *
     * @example
     * ```tsx
     * tooltip={{
     *     render: (ctx) => <InsightTooltip seriesData={toSeriesDatum(ctx)} />,
     * }}
     * ```
     */
    render?: (context: TooltipContext) => React.ReactNode
    /**
     * Called when the tooltip should hide (mouse leaves the chart area).
     * Useful for cleaning up custom tooltip state.
     */
    onHide?: () => void
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

export interface HogChartTheme {
    /** Ordered palette of hex colors for series auto-coloring. */
    colors: string[]
    /** Font family for all text. */
    fontFamily?: string
    /** Base font size in px. */
    fontSize?: number
    /** Background color of the chart area. */
    backgroundColor?: string
    /** Color for axis lines, ticks, and labels. */
    axisColor?: string
    /** Color for grid lines. */
    gridColor?: string
    /** Color for goal lines when not overridden. */
    goalLineColor?: string
    /** Tooltip background. */
    tooltipBackground?: string
    /** Tooltip text color. */
    tooltipColor?: string
    /** Border radius for tooltips. */
    tooltipBorderRadius?: number
}

// ---------------------------------------------------------------------------
// Shared chart props (every chart component extends these)
// ---------------------------------------------------------------------------

export interface BaseChartProps {
    /** Chart width — CSS value or number (px). Defaults to `"100%"`. */
    width?: number | string
    /** Chart height — CSS value or number (px). Defaults to `300`. */
    height?: number | string
    /** Theme overrides. Merged with the default HogCharts theme. */
    theme?: Partial<HogChartTheme>
    /** Legend configuration. */
    legend?: LegendConfig
    /** Tooltip configuration. */
    tooltip?: TooltipConfig
    /** Additional CSS class name on the wrapper. */
    className?: string
    /** Whether to animate transitions. Defaults to `false`. */
    animate?: boolean
    /** Accessible label for screen readers. */
    ariaLabel?: string
    /** Callback when a data point is clicked. */
    onClick?: (point: ClickEvent) => void
}

export interface ClickEvent {
    /** Index of the clicked series. */
    seriesIndex: number
    /** Index of the clicked data point within the series. */
    pointIndex: number
    /** The raw numeric value. */
    value: number
    /** The label of the point on the x-axis. */
    label: string
    /** The series label. */
    seriesLabel: string
    /** The `meta` bag from the series, if provided. */
    meta?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Time-series chart props (Line, Bar, Area, StackedBar)
// ---------------------------------------------------------------------------

export interface TimeSeriesProps extends BaseChartProps {
    /** One or more data series. */
    data: Series[]
    /** Optional comparison series (e.g. previous period). */
    compare?: ComparisonSeries[]
    /** Shared x-axis labels — one per data point. */
    labels: string[]
    /** X-axis configuration. */
    xAxis?: AxisConfig
    /** Y-axis configuration. Pass an array for dual y-axes `[left, right]`. */
    yAxis?: AxisConfig | [AxisConfig, AxisConfig]
    /** Horizontal goal/target lines. */
    goalLines?: GoalLine[]
    /** Vertical annotation markers. */
    annotations?: Annotation[]
    /** Show values directly on the chart. Defaults to `false`. */
    showValues?: boolean
    /** Show a trend line for each series. */
    showTrendLine?: boolean

    // -- Time context (enables smart x-axis formatting) ----------------------

    /**
     * Raw date/datetime strings for each data point (e.g. `"2025-03-01"` or
     * `"2025-03-01 14:00:00"`). When provided, hog-charts auto-formats x-axis
     * ticks with smart date labels (month names, day labels, HH:mm, etc.).
     *
     * These are the raw ISO dates from the query, not the display labels.
     * The `labels` prop is still used as Chart.js category labels.
     */
    days?: (string | number)[]
    /**
     * Time interval granularity of the data. Helps hog-charts pick the right
     * tick format (month names vs day labels vs HH:mm). When omitted, the
     * interval is inferred from the `days` spacing.
     */
    interval?: ChartInterval
    /**
     * IANA timezone string (e.g. `"America/New_York"`, `"UTC"`).
     * Used for timezone-aware x-axis tick formatting. Defaults to `"UTC"`.
     */
    timezone?: string

    /**
     * Custom x-axis tick callback. When provided, overrides the default
     * smart date formatting. Receives the raw tick value and index, returns
     * the formatted label string or `null` to hide the tick.
     */
    xAxisTickCallback?: (value: string | number, index: number) => string | null
}

// ---------------------------------------------------------------------------
// Line-specific
// ---------------------------------------------------------------------------

export type LineStyle = 'solid' | 'dashed' | 'dotted'
export type LineInterpolation = 'linear' | 'smooth' | 'step'

export interface LineProps extends TimeSeriesProps {
    /** Cumulative mode — each point is the running total. */
    cumulative?: boolean
    /** Line interpolation. Defaults to `"linear"`. */
    interpolation?: LineInterpolation
    /** Show data point dots. Defaults to `"auto"` (shown when ≤ 30 points). */
    showDots?: boolean | 'auto'
    /** Line width in px. Defaults to `2`. */
    lineWidth?: number

    // -- Stacking ------------------------------------------------------------

    /** Stack all series. Defaults to `false`. */
    stacked?: boolean
    /** Show as 100% stacked (percent stack view). Implies `stacked: true`. */
    stacked100?: boolean

    // -- Area fill -----------------------------------------------------------

    /** Fill under all series (area chart mode). Defaults to `false`. */
    isArea?: boolean
    /** Fill opacity when `isArea` is true. Defaults to `0.5`. */
    fillOpacity?: number

    // -- Axis visibility & scale ---------------------------------------------

    /** Hide the x-axis entirely. */
    hideXAxis?: boolean
    /** Hide the y-axis entirely. */
    hideYAxis?: boolean

    // -- Crosshair -----------------------------------------------------------

    /** Show a vertical crosshair on hover. Defaults to `true` for line, `false` for bar. */
    crosshair?: boolean

    // -- Incompleteness (in-progress data) -----------------------------------

    /**
     * Number of data points at the end of each series to render as
     * "incomplete" (dotted line). Used for the current, still-accumulating
     * time period. Set to `0` to disable. Defaults to `0`.
     */
    incompletenessOffset?: number

    // -- Series highlighting (shift-hover on stacked bars) -------------------

    /** Index of the series to visually highlight. `null` = no highlight. */
    highlightSeriesIndex?: number | null
    /** Called when hover state changes. Used for shift-hover bar highlighting. */
    onHighlightChange?: (seriesIndex: number | null) => void

    // -- Limits --------------------------------------------------------------

    /** Maximum number of datasets to render. Excess series are dropped. */
    maxSeries?: number
}

// ---------------------------------------------------------------------------
// Area-specific
// ---------------------------------------------------------------------------

export interface AreaProps extends LineProps {
    /** Fill opacity (0–1). Defaults to `0.1`. */
    fillOpacity?: number
    /** Stack areas. Defaults to `false`. */
    stacked?: boolean
    /** Show as 100% stacked. Implies `stacked: true`. */
    stacked100?: boolean
}

// ---------------------------------------------------------------------------
// Bar-specific
// ---------------------------------------------------------------------------

export type BarOrientation = 'vertical' | 'horizontal'

export interface BarProps extends TimeSeriesProps {
    /** Stack bars. Defaults to `false`. */
    stacked?: boolean
    /** Show as 100% stacked. Implies `stacked: true`. */
    stacked100?: boolean
    /** Bar orientation. Defaults to `"vertical"`. */
    orientation?: BarOrientation
    /** Border radius on bars in px. Defaults to `4`. */
    borderRadius?: number
    /** Gap between bar groups as fraction (0–1). Defaults to `0.3`. */
    barGap?: number
}

// ---------------------------------------------------------------------------
// Pie / Donut
// ---------------------------------------------------------------------------

export interface PieSlice {
    label: string
    value: number
    color?: string
    /** Opaque metadata bag passed through to tooltip context. */
    meta?: Record<string, unknown>
}

export interface PieProps extends BaseChartProps {
    data: PieSlice[]
    /** Render as donut (hollow center). Defaults to `true`. */
    donut?: boolean
    /** Donut hole size as fraction (0–1). Defaults to `0.6`. */
    innerRadius?: number
    /** Show percentage labels. Defaults to `true`. */
    showLabels?: boolean
    /** Show values on slices. */
    showValues?: boolean
}

// ---------------------------------------------------------------------------
// Number (bold KPI)
// ---------------------------------------------------------------------------

export interface NumberProps extends BaseChartProps {
    /** The primary value to display. */
    value: number
    /** Previous value for comparison. Renders a delta indicator. */
    previousValue?: number
    /** Label shown below the number. */
    label?: string
    /** Format for the number. Defaults to `"compact"`. */
    format?: AxisFormat
    /** Prefix (e.g. `"$"`). */
    prefix?: string
    /** Suffix (e.g. `"users"`). */
    suffix?: string
}

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------

export interface FunnelStep {
    /** Step label (e.g. "Sign up"). */
    label: string
    /** Number of users/events at this step. */
    count: number
    /** Optional breakdown of this step by a dimension. */
    breakdown?: { label: string; count: number }[]
    /** Median time from previous step (in seconds). */
    medianTime?: number
}

export type FunnelLayout = 'horizontal' | 'vertical'
export type FunnelVizType = 'steps' | 'time_to_convert' | 'trends'

export interface FunnelProps extends BaseChartProps {
    steps: FunnelStep[]
    /** Layout direction. Defaults to `"horizontal"`. */
    layout?: FunnelLayout
    /** Visualization sub-type. Defaults to `"steps"`. */
    vizType?: FunnelVizType
    /** Show conversion rate between steps. Defaults to `true`. */
    showConversionRates?: boolean
    /** Show median conversion time. Defaults to `false`. */
    showTime?: boolean
    /** Goal lines (only for `vizType: "trends"`). */
    goalLines?: GoalLine[]
}

// ---------------------------------------------------------------------------
// Retention
// ---------------------------------------------------------------------------

export interface RetentionCohort {
    /** Cohort label (e.g. "Week 0", "Jan 1"). */
    label: string
    /** Date string for the cohort start. */
    date: string
    /** Retention values — index 0 is the cohort size, rest are retention counts. */
    values: number[]
}

export type RetentionPeriod = 'hour' | 'day' | 'week' | 'month'

export interface RetentionProps extends BaseChartProps {
    data: RetentionCohort[]
    /** Labels for the retention columns (e.g. "Day 0", "Day 1", ...). */
    periodLabels: string[]
    /** Time period granularity. Defaults to `"day"`. */
    period?: RetentionPeriod
    /** Show values as percentages. Defaults to `true`. */
    showPercentages?: boolean
    /** Show raw counts alongside percentages. */
    showCounts?: boolean
}

// ---------------------------------------------------------------------------
// Paths (Sankey-like)
// ---------------------------------------------------------------------------

export interface PathNode {
    name: string
    /** Number of users at this node. */
    count: number
}

export interface PathLink {
    source: string
    target: string
    value: number
    /** Average time between source and target (seconds). */
    averageTime?: number
}

export interface PathsProps extends BaseChartProps {
    nodes: PathNode[]
    links: PathLink[]
    /** Maximum number of paths to show. Defaults to `50`. */
    maxPaths?: number
    /** Highlight a specific path on hover. */
    highlightPath?: string[]
}

// ---------------------------------------------------------------------------
// World Map (Choropleth)
// ---------------------------------------------------------------------------

export interface MapDataPoint {
    /** ISO 3166-1 alpha-2 country code. */
    code: string
    /** Value for the country. */
    value: number
    /** Optional label override. */
    label?: string
}

export interface WorldMapProps extends BaseChartProps {
    data: MapDataPoint[]
    /** Color scale — from low to high. Defaults to theme gradient. */
    colorRange?: [string, string]
    /** Show country labels on hover. Defaults to `true`. */
    showLabels?: boolean
}

// ---------------------------------------------------------------------------
// Box Plot
// ---------------------------------------------------------------------------

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
    /** X-axis configuration. */
    xAxis?: AxisConfig
    /** Y-axis configuration. */
    yAxis?: AxisConfig
    /** Show mean marker. Defaults to `true`. */
    showMean?: boolean
    /** Show outlier points. Defaults to `true`. */
    showOutliers?: boolean
}

// ---------------------------------------------------------------------------
// Heatmap
// ---------------------------------------------------------------------------

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
    /** Color gradient stops — `[low, high]` or `[low, mid, high]`. */
    colorRange?: string[]
    /** Show values in cells. Defaults to `true`. */
    showValues?: boolean
    /** Border radius on cells in px. Defaults to `2`. */
    borderRadius?: number
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

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
    /** Colors for each lifecycle status. Uses theme defaults if omitted. */
    statusColors?: Partial<Record<LifecycleStatus, string>>
    /** Toggle which statuses are visible. All shown by default. */
    visibleStatuses?: LifecycleStatus[]
    showValues?: boolean
}

// ---------------------------------------------------------------------------
// Stickiness
// ---------------------------------------------------------------------------

export interface StickinessProps extends TimeSeriesProps {
    /** X-axis represents "number of days active". Override label defaults. */
    xAxis?: AxisConfig
}

// ---------------------------------------------------------------------------
// The universal HogChart component discriminated union
// ---------------------------------------------------------------------------

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
