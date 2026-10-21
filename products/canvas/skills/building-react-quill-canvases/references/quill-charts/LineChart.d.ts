// Types of `LineChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, PointClickData, DateRangeZoomData, SeriesType, ChartConfig, ValueDomain, ChartLegendConfig, LabelRange, AxisLinesConfig, TooltipConfig, ChartMargins, YAxis, LegendItem, LegendItemControls.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': LineChart, LineChartProps, LineChartConfig.
// Other declarations here are shapes to match, not names to import.

export declare function LineChart<Meta = unknown>({ onError, ...rest }: LineChartProps<Meta>): React.ReactElement

export interface LineChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: LineChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    onDateRangeZoom?: (data: DateRangeZoomData) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface LineChartConfig extends ChartConfig {
    percentStackView?: boolean
    /** Value-axis domain control — omit for data-derived auto-scaling. See {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Float the value axis to its data range instead of clamping the baseline to 0 (a y-axis "start
     *  at zero = off"). Applied to the primary axis only; ignored on a log scale. Defaults to false. */
    floatBaseline?: boolean
    /** Built-in legend with click-to-toggle series visibility. Hidden by default. */
    legend?: ChartLegendConfig
}
