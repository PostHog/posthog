// Types of `BarList`. Shared types it uses, declared in core.d.ts: Series, ChartTheme, TooltipContext, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': BarList, BarListProps, BarListConfig.
// Other declarations here are shapes to match, not names to import.

export declare function BarList<Meta = unknown>({ onError, ...rest }: BarListProps<Meta>): React.ReactElement

/** Shares `series` and `valueFormatter` with `PieChart` and `ProportionBar`. */
export interface BarListProps<Meta = unknown> {
    /** One series per row, valued like a `PieChart` slice: the sum of `data`, floored at 0. Rows
     *  keep the order of `series`, so sort them before you pass them in. */
    series: Series<Meta>[]
    theme: ChartTheme
    config?: BarListConfig
    /** The whole that each share is a fraction of. Defaults to the sum of the rows. Set it when the
     *  rows are the top of a larger whole, so the shares stay true to that whole. */
    total?: number
    /** Formats a row's raw value in the value column and the tooltip. */
    valueFormatter?: (value: number) => string
    /** Content of a row's label cell, for example an icon and a link. Defaults to the series label.
     *  The cell is a flex row that truncates, so wrap long text in a `truncate` element. */
    renderLabel?: (series: Series<Meta>) => React.ReactNode
    /** Replaces the default tooltip. `ctx.seriesData[0].series.meta` is the `meta` of the hovered row. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export interface BarListConfig {
    /** `start` (default) puts the label left of the bar and the value right of it. `top` puts the
     *  label and the value on one line above the bar, so the bar and a long label get the full width. */
    labelPosition?: 'start' | 'top'
    /** `max` (default) fills the track with the largest row, to compare the rows with each other.
     *  `total` makes the track the whole, so each bar shows its share of `total`. */
    scale?: 'max' | 'total'
    /** What the value column shows: the formatted value, its share of the total, or both as
     *  `share · value`. Default `value`. With `labelPosition: 'start'`, a list narrower than 28rem
     *  shows only the share for `both`, and the tooltip still shows the value. */
    valueDisplay?: 'value' | 'percent' | 'both'
    /** Row height in px, label line included. Default 28, or 40 with `labelPosition: 'top'`. */
    rowHeight?: number
    /** Bar thickness in px. Default 12, or 8 with `labelPosition: 'top'`. */
    barHeight?: number
    /** Corner radius in px for the bar and its track. Default 4. */
    barCornerRadius?: number
    tooltip?: {
        enabled?: boolean
    }
}
