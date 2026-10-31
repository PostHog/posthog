// Types of `ProportionBar`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, RadialSlicePayload, SeriesType, ChartLegendConfig, ResolvedSeries, LegendItem, LegendItemControls.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': ProportionBar, ProportionBarProps, ProportionBarConfig.
// Other declarations here are shapes to match, not names to import.

export declare function ProportionBar<Meta = unknown>({
    onError,
    ...rest
}: ProportionBarProps<Meta>): React.ReactElement

/** Shares `series`, `valueFormatter`, `tooltip`, `onSliceClick` and `config.legend` with `PieChart`.
 *  It has no `isPercent`, `sliceValueDisplay` or `config.sliceValue`: the bar always shows each
 *  part's share and value, and always values a part as the sum of its data. */
export interface ProportionBarProps<Meta = unknown> {
    /** One series per part, valued like a `PieChart` slice: the sum of `data`, floored at 0. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: ProportionBarConfig
    /** Formats a part's raw value in the legend and the default tooltip. */
    valueFormatter?: (value: number) => string
    /** Replaces the default tooltip. As on `PieChart`, `ctx.seriesData[0]` is the hovered part,
     *  with its raw `value` and its `fraction` of the visible parts. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface ProportionBarConfig {
    /** Bar thickness in px. Default 24. */
    barHeight?: number
    /** Corner radius in px for both ends of the bar. Default 6. */
    barCornerRadius?: number
    /** Legend with one row per part and `share · value` on each row. Unlike the other charts it
     *  shows by default, at the bottom and start-aligned, because the bar has no axis to read a
     *  size from. Same click model as the other charts. */
    legend?: ChartLegendConfig
    tooltip?: {
        enabled?: boolean
    }
}
