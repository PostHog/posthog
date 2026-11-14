// Types of `ComboChart`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, PointClickData, SeriesType, ChartConfig, ValueDomain, AxisLinesConfig, TooltipConfig, ChartMargins, YAxis, DefaultTooltipProps, SeriesDatum.
// Generated from @posthog/quill-charts 0.3.0-beta.33, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': ComboChart, ComboChartProps, ComboChartConfig.
// Other declarations here are shapes to match, not names to import.

export declare function ComboChart<Meta = unknown>({ onError, ...rest }: ComboChartProps<Meta>): React.ReactElement

export interface ComboChartProps<Meta = unknown> {
    series: Series<Meta>[]
    labels: string[]
    config?: ComboChartConfig
    /** Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars. */
    theme?: ChartTheme
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onPointClick?: (data: PointClickData<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. See `ChartProps.dataAttr`. */
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Config for {@link ComboChart}, which draws bar, line, and area series together. `axisOrientation`
 *  is omitted on purpose — bars require a band x-axis, so combo charts are vertical-only. */
export interface ComboChartConfig extends Omit<ChartConfig, 'axisOrientation'> {
    /** Gap between bar bands (0–1, default 0.2). Zero also removes within-group spacing. */
    bandPadding?: number
    /** Type used for series that don't set {@link Series.type}. Defaults to `'line'`. */
    defaultSeriesType?: SeriesType
    /** Layout applied to *bar* series only — lines and areas never stack or group. Defaults to
     *  `'stacked'`. `'percent'` stacks bars to 100%; line/area series still plot at raw values. */
    barLayout?: 'stacked' | 'grouped' | 'percent'
    /** Stacked layout only — use d3.stackOffsetDiverging so negative bar values stack below the
     *  zero baseline (positives above). A stacked layout with a negative bar value uses it without
     *  this flag. Mirrors {@link BarsConfig.divergingStack}. */
    divergingStack?: boolean
    /** Corner radius for the cap of bar segments. Stacked bars only round the topmost segment. */
    barCornerRadius?: number
    /** Value-axis domain control for the primary axis — omit for data-derived auto-scaling. Used
     *  to keep off-scale goal lines on-plot (`{ include }`). See {@link ValueDomain}. */
    valueDomain?: ValueDomain
    /** Primary-axis `min` / `max`, honored only while that axis carries no bar series: a bar encodes
     *  magnitude as length from zero, so a raised floor would misread it. Use `valueDomain` to rescale
     *  an axis with bars. `valueDomain` wins a bound both set. */
    valueBounds?: Pick<ValueDomain, 'min' | 'max'>
    /** Float the primary axis to its data range instead of clamping the baseline to 0. Ignored while
     *  the axis carries bar series, and on a log scale. Defaults to false. */
    floatBaseline?: boolean
}
