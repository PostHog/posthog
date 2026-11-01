// Types of `SlopeChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, PointClickData, SeriesType, ChartConfig, ValueDomain, AxisLinesConfig, TooltipConfig, ChartMargins, YAxis, ChartLegendConfig, LegendItem, LegendItemControls.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': SlopeChart, SlopeSeriesMeta, SlopeChartProps, SlopeChartConfig, SlopeChartLegendConfig.
// Other declarations here are shapes to match, not names to import.

export declare function SlopeChart<Meta = SlopeSeriesMeta>({
    onError,
    ...rest
}: SlopeChartProps<Meta>): React.ReactElement

/** Per-series options read from `Series.meta` by the slope chart. Lets a consumer toggle the
 *  start/end value labels for an individual series without touching the shared `Series` type. */
export interface SlopeSeriesMeta {
    /** Show this series' start (left) value label. Falls back to the chart-level default. */
    showStartLabel?: boolean
    /** Show this series' end (right) value label. Falls back to the chart-level default. */
    showEndLabel?: boolean
    /** The last point is the current, still-accumulating period. The chart dashes only the second
     *  half of the connector to show the end — not the whole comparison — is provisional. */
    incompleteEnd?: boolean
}

export interface SlopeChartProps<Meta = SlopeSeriesMeta> {
    series: Series<Meta>[]
    labels: string[]
    config?: SlopeChartConfig
    theme: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface SlopeChartConfig extends ChartConfig {
    /** Show the series name labels beside each series' last point. Default true. */
    showSeriesLabels?: boolean
    /** Default for the start (left) value labels; per-series `meta.showStartLabel` overrides. Default true. */
    showStartLabels?: boolean
    /** Default for the end (right) value labels; per-series `meta.showEndLabel` overrides. Default true. */
    showEndLabels?: boolean
    /** Legend visibility + placement. Hidden by default. */
    legend?: SlopeChartLegendConfig
    /** Formats the start/end value labels. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number) => string
    /** Formats the per-series change shown in the legend. Defaults to a signed `toLocaleString`. */
    deltaFormatter?: (delta: number) => string
    /** Radius of the point markers in px. Default 4. */
    pointRadius?: number
    /** Value-axis domain control — omit for data-derived auto-scaling. */
    valueDomain?: ValueDomain
}

/** Slope-chart legend config. Same shape as every chart's {@link ChartLegendConfig} — clicking a
 *  row toggles that series (interactive by default). Rows carry the per-series change. */
export type SlopeChartLegendConfig = ChartLegendConfig
