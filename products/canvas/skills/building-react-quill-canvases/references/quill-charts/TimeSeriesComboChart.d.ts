// Types of `TimeSeriesComboChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, PointClickData, SeriesType, XAxisConfig, YAxisConfig, ValueLabelsConfig, GoalLineConfig, AxisLinesConfig, TooltipConfig, ChartLegendConfig, TrendLineConfig, ChartConfig, ValueDomain, TimeInterval, YFormatterConfig, ValueLabelFormatter, LegendItem, LegendItemControls, ChartMargins, YAxis, YAxisFormat, ValueLabelContext.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': TimeSeriesComboChart, TimeSeriesComboChartProps, TimeSeriesComboChartConfig, ComboChartConfig.
// Other declarations here are shapes to match, not names to import.

/** Time-indexed {@link ComboChart}: mixed bar + line/area series on a timezone/interval-aware band
 *  x-axis, plus the time-series chrome `ComboChart` lacks — date x-axis, goal lines, a built-in
 *  legend, and value labels. Mirrors {@link TimeSeriesBarChart}/{@link TimeSeriesLineChart}. */
export declare function TimeSeriesComboChart<Meta = unknown>({
    series,
    labels,
    theme,
    config,
    tooltip,
    onPointClick,
    dataAttr,
    className,
    children,
    onError,
}: TimeSeriesComboChartProps<Meta>): React.ReactElement

export interface TimeSeriesComboChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: TimeSeriesComboChartConfig
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    dataAttr?: string
    className?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface TimeSeriesComboChartConfig {
    /** Reserve space for custom overlays; unspecified sides keep their computed margins. */
    margins?: ComboChartConfig['margins']
    xAxis?: XAxisConfig
    /** Single object for a standard left axis; array for dual left+right axes. */
    yAxis?: YAxisConfig | YAxisConfig[]
    valueLabels?: boolean | ValueLabelsConfig
    goalLines?: GoalLineConfig[]
    /** Type used for series that don't set {@link Series.type}. Defaults to `'line'`. */
    defaultSeriesType?: SeriesType
    /** Layout applied to *bar* series only — lines and areas never stack or group. Defaults to
     *  `'stacked'`. */
    barLayout?: ComboChartConfig['barLayout']
    /** Stacked layout only — stack negative bar values below the zero baseline instead of
     *  clamping them to 0. See {@link ComboChartConfig.divergingStack}. */
    divergingStack?: boolean
    /** Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Show a vertical crosshair line that follows the cursor. */
    showCrosshair?: boolean
    /** Horizontal grid lines, aligned to the primary y-axis ticks. `showGrid` on the primary
     *  `yAxis` config, when set, wins. */
    showGrid?: boolean
    /** Draw L-shaped axis baselines without grid lines (ignored when `yAxis.showGrid` is true). */
    showAxisLines?: AxisLinesConfig
    /** Draw short tick marks next to each visible axis label. Pairs with `showAxisLines`. */
    showTickMarks?: boolean
    /** Line interpolation for line/area series: `linear` (default) or `monotone` (smooth curve). */
    curve?: 'linear' | 'monotone'
    /** Tooltip behaviour (pinning, placement). Tooltip *content* is the `tooltip` render prop. */
    tooltip?: TooltipConfig
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
    /** Trend line overlays rendered as SVG lines on top of the chart. */
    trendLines?: TrendLineConfig[]
}

/** Config for {@link ComboChart}, which draws bar, line, and area series together. `axisOrientation`
 *  is omitted on purpose — bars require a band x-axis, so combo charts are vertical-only. */
export interface ComboChartConfig extends Omit<ChartConfig, 'axisOrientation'> {
    /** Type used for series that don't set {@link Series.type}. Defaults to `'line'`. */
    defaultSeriesType?: SeriesType
    /** Layout applied to *bar* series only — lines and areas never stack or group. Defaults to
     *  `'stacked'`. `'percent'` stacks bars to 100%; line/area series still plot at raw values. */
    barLayout?: 'stacked' | 'grouped' | 'percent'
    /** Stacked layout only — use d3.stackOffsetDiverging so negative bar values stack below the
     *  zero baseline (positives above). Default `false` clamps negatives to 0. Mirrors
     *  {@link BarsConfig.divergingStack}. */
    divergingStack?: boolean
    /** Corner radius for the cap of bar segments. Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Value-axis domain control for the primary axis — omit for data-derived auto-scaling. Used
     *  to keep off-scale goal lines on-plot (`{ include }`). See {@link ValueDomain}. */
    valueDomain?: ValueDomain
}
