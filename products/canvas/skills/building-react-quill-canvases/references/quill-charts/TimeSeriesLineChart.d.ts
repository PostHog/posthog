// Types of `TimeSeriesLineChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, PointClickData, DateRangeZoomData, SeriesType, XAxisConfig, YAxisConfig, ValueLabelsConfig, GoalLineConfig, TrendLineConfig, AxisLinesConfig, TooltipConfig, ChartLegendConfig, LabelRange, ChartConfig, ValueDomain, TimeInterval, YFormatterConfig, ValueLabelsProps, ValueLabelFormatter, ReferenceLineStroke, DefaultTooltipProps, LegendItem, LegendItemControls, LegendTableConfig, ChartMargins, YAxis, YAxisFormat, ValueLabelsMode, ValueLabelContext, SeriesDatum, LegendValue.
// Generated from @posthog/quill-charts 0.3.0-beta.33, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': TimeSeriesLineChart, TimeSeriesLineChartProps, TimeSeriesLineChartConfig, LineChartConfig, ConfidenceIntervalConfig, MovingAverageConfig, TimeScale.
// Other declarations here are shapes to match, not names to import.

export declare function TimeSeriesLineChart<Meta = unknown>({
    series,
    labels,
    theme: themeProp,
    config,
    tooltip,
    onPointClick,
    onPointContextMenu,
    onDateRangeZoom,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesLineChartProps<Meta>): React.ReactElement

export interface TimeSeriesLineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    /** One x value per data index, unique across the array (use ISO date strings, not formatted
     *  display labels). The x-scale keys positions off these strings, so a repeated value
     *  collapses onto the first occurrence's position and draws the series backwards. Display
     *  formatting belongs in `xAxis.timezone`/`interval` (auto tick formatter) or `tickFormatter`. */
    labels: string[]
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    config?: TimeSeriesLineChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    /** Right-click counterpart of `onPointClick`. See `ChartProps.onPointContextMenu`. */
    onPointContextMenu?: (data: PointClickData<Meta>) => void
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface TimeSeriesLineChartConfig {
    valueDomain?: LineChartConfig['valueDomain']
    /** Reserve space for custom overlays; unspecified sides keep their computed margins. */
    margins?: LineChartConfig['margins']
    xAxis?: XAxisConfig
    /** Single object = one y-axis (today's behavior). Array = one entry per axis for dual y-axis
     *  charts: set `id` (matches `Series.yAxisId`; first entry defaults to `'left'`) and `position`
     *  (`'left'`/`'right'`; first entry defaults to `'left'`, the rest to `'right'`). A series renders
     *  against a secondary axis when its `yAxisId` matches an entry's `id`. */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    confidenceIntervals?: ConfidenceIntervalConfig[]
    movingAverage?: MovingAverageConfig[]
    trendLines?: TrendLineConfig[]
    /** Comparison series keys mapped to their primary. Comparison series render dimmed. */
    comparisonOf?: Record<string, string>
    /** Render area-fill series as a 100% stacked view; y-axis becomes 0–100%. */
    percentStackView?: boolean
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Horizontal grid lines, aligned to the primary y-axis ticks. `showGrid` on the primary
     *  `yAxis` config, when set, wins. */
    showGrid?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: AxisLinesConfig
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Line interpolation: `linear` (default) or `monotone` (smooth curve through every point). */
    curve?: 'linear' | 'monotone'
    /** `time` places each point at its time, so uneven spacing and gaps in time show. Labels must
     *  be ascending. Moving averages still use sample order. Defaults to `index`. */
    xScale?: 'index' | 'time'
    /** With `xScale: 'time'`, the axis span as `[from, to]` epoch ms. Defaults to the label range. */
    xDomain?: readonly [number, number]
    /** Draw lines and areas across missing (non-finite) values instead of breaking them. */
    connectNulls?: boolean
    /** Tooltip behaviour and built-in content options. A `tooltip` render prop replaces the content. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface LineChartConfig extends ChartConfig {
    percentStackView?: boolean
    /** Place each label at its time instead of evenly by index. Labels must be ascending. Memoize it. */
    timeScale?: TimeScale
    /** Draw lines and areas across missing (non-finite) values instead of breaking them. */
    connectNulls?: boolean
    /** Value-axis domain control — omit for data-derived auto-scaling. See {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Float the value axis to its data range instead of clamping the baseline to 0 (a y-axis "start
     *  at zero = off"). Applied to the primary axis only; ignored on a log scale. Defaults to false. */
    floatBaseline?: boolean
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}

export interface ConfidenceIntervalConfig {
    seriesKey: string
    lower: number[]
    upper: number[]
}

export interface MovingAverageConfig {
    seriesKey: string
    window: number
    label?: string
}

export interface TimeScale {
    parse: (label: string) => number
    domain: readonly [number, number]
}
