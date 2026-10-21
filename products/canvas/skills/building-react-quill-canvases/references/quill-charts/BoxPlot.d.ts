// Types of `BoxPlot`. Shared types it uses, declared in core.d.ts: ChartTheme, ChartConfig, ChartLegendConfig, TooltipContext, AxisLinesConfig, TooltipConfig, ChartMargins, YAxis, LegendItem, LegendItemControls, Series, ValueDomain, SeriesType.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': BoxPlot, BoxPlotProps, BoxPlotSeries, BoxPlotConfig, BoxPlotTooltipContext, BoxPlotClickData, BoxPlotDatum, BoxPlotAdaptedMeta.
// Other declarations here are shapes to match, not names to import.

export declare function BoxPlot<Meta = unknown>({ onError, ...rest }: BoxPlotProps<Meta>): React.ReactElement

export interface BoxPlotProps<Meta = unknown> {
    series: BoxPlotSeries<Meta>[]
    labels: string[]
    theme: ChartTheme
    config?: BoxPlotConfig
    /** Optional custom tooltip. Receives the adapter `TooltipContext`; consumers can read
     *  the original datum back out via `entry.series.meta?.datums?.[ctx.dataIndex]`. */
    tooltip?: (ctx: BoxPlotTooltipContext<Meta>) => React.ReactNode
    /** Click callback — fired when the user clicks a box. The product layer wires this to
     *  the persons modal in the BoxPlot insight. */
    onBoxClick?: (data: BoxPlotClickData<Meta>) => void
    className?: string
    dataAttr?: string
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

/** Series shape for the BoxPlot chart. Unlike the generic `Series` (whose `data` is
 *  `number[]`), each entry is a six-number summary. `data.length` must match the chart's
 *  `labels.length`; entries may be `null` for missing x positions. */
export interface BoxPlotSeries<Meta = unknown> {
    /** Unique identifier — used for React keys, scale group keys, and tooltip joins. */
    key: string
    /** Human-readable label used in legends/tooltips. */
    label: string
    /** Optional CSS color. When omitted (or empty), the chart picks one from `theme.colors`. */
    color?: string
    /** One six-number summary per x label, or `null` for missing data at that index. */
    data: (BoxPlotDatum | null)[]
    /** Free-form metadata flowed through to tooltip / click handlers. */
    meta?: Meta
    /** Visibility controls. Mirrors `Series.visibility` but with only the flags BoxPlot honors. */
    visibility?: {
        excluded?: boolean
        tooltip?: boolean
    }
}

/** Chart-level config. `axisOrientation: 'horizontal'` lists the labels down the y-axis and draws
 *  the value axis along x, which suits a few long boxes better than a row of narrow columns. */
export interface BoxPlotConfig extends ChartConfig {
    legend?: ChartLegendConfig
    /** Mean marker radius in CSS pixels. Defaults to 3. */
    meanRadius?: number
    /** Whisker cap width as a fraction of the box width. Defaults to 0.6. */
    whiskerCapRatio?: number
    /** Box outline / whisker stroke width. Defaults to 1.5. */
    boxStrokeWidth?: number
}

/** Tooltip context handed to consumer-supplied `tooltip` callbacks. Same shape as
 *  `TooltipContext` but with the `BoxPlotAdaptedMeta` `Meta` parameter baked in so consumers
 *  don't have to redeclare it. */
export type BoxPlotTooltipContext<Meta = unknown> = TooltipContext<BoxPlotAdaptedMeta<Meta>>

export interface BoxPlotClickData<Meta = unknown> {
    /** The *first visible series* at the clicked column — matches BarChart's `onPointClick`
     *  contract. In grouped mode this is **not necessarily the series under the cursor**: when
     *  the user clicks series B's sub-band, `series` is still A. The product layer should
     *  narrow via `crossSeriesData` + the cursor x if it needs the precise box. */
    series: BoxPlotSeries<Meta>
    /** Index of `series` in the input `series` array (first-visible, not under-cursor). */
    seriesIndex: number
    /** Index along the x-axis (into `labels`). */
    dataIndex: number
    /** The x-axis label at this index. */
    label: string
    /** The six-number summary on `series` at this column. */
    datum: BoxPlotDatum
    /** All visible boxes at this column, in render order, for cross-series comparisons. */
    crossSeriesData: {
        series: BoxPlotSeries<Meta>
        datum: BoxPlotDatum
    }[]
}

/** Six-number summary plus an opaque `day` identifier (`day` is the consumer-side key for click
 *  handlers / persons-modal labels). */
export type BoxPlotDatum = BoxPlotSummary & {
    /** Optional identifier for this x position (e.g. ISO date). The chart treats it as opaque. */
    day?: string
}

/** Meta attached to the inner adapter `Series` we hand to the `Chart` base — carries the
 *  original six-number summaries indexed by x-position, plus any user-supplied meta. Exported
 *  so consumers with a custom `tooltip` can read the original datum back out of
 *  `entry.series.meta?.datums?.[ctx.dataIndex]`. */
export interface BoxPlotAdaptedMeta<Meta = unknown> {
    datums: (BoxPlotDatum | null)[]
    user?: Meta
}

/** The six-number summary the chart renders. Kept structurally compatible with the canonical
 *  `BoxPlotDatum` in the frontend's `queries/schema-general.ts` so consumers can pass it directly. */
type BoxPlotSummary = {
    min: number
    p25: number
    median: number
    mean: number
    p75: number
    max: number
}
