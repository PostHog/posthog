/** The six-number summary the chart renders. Kept structurally compatible with the canonical
 *  `BoxPlotDatum` in the frontend's `queries/schema-general.ts` so consumers can pass it directly. */
type BoxPlotSummary = { min: number; p25: number; median: number; mean: number; p75: number; max: number }

/** Six-number summary plus an opaque `day` identifier (`day` is the consumer-side key for click
 *  handlers / persons-modal labels). */
export type BoxPlotDatum = BoxPlotSummary & {
    /** Optional identifier for this x position (e.g. ISO date). The chart treats it as opaque. */
    day?: string
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
