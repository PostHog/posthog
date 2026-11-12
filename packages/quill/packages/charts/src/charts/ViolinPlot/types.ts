/** The raw observations behind one violin. The chart derives the shape, the median and the mean
 *  from them, so a consumer passes the values, not a summary.
 *
 *  The sorted values are cached against the datum object, so do not change `values` in place:
 *  pass a new datum (or a new array in a new datum) when the observations change. */
export interface ViolinPlotDatum {
    /** Every observation in this group. Non-finite values are ignored. */
    values: number[]
}

/** Series shape for the ViolinPlot chart. Unlike the generic `Series` (whose `data` is
 *  `number[]`), each entry holds the observations behind one violin. `data.length` must match
 *  the chart's `labels.length`; entries may be `null` for missing x positions. */
export interface ViolinPlotSeries<Meta = unknown> {
    /** Unique identifier — used for React keys, scale group keys, and tooltip joins. */
    key: string
    /** Human-readable label used in legends/tooltips. */
    label: string
    /** Optional CSS color. When omitted (or empty), the chart picks one from `theme.colors`. */
    color?: string
    /** One set of observations per x label, or `null` for missing data at that index. */
    data: (ViolinPlotDatum | null)[]
    /** Free-form metadata flowed through to tooltip handlers. */
    meta?: Meta
    /** Visibility controls. Mirrors `Series.visibility` but with only the flags ViolinPlot honors. */
    visibility?: {
        excluded?: boolean
        tooltip?: boolean
    }
}

/** Summary statistics of one violin's observations, shown in the tooltip. */
export interface ViolinSummary {
    count: number
    min: number
    p25: number
    median: number
    mean: number
    p75: number
    max: number
}

/** A laid-out violin for a single (series, x) slot — pre-computed pixel coordinates so the draw
 *  functions don't touch scales. */
export interface ViolinRect {
    /** Left edge of the slot the violin sits in. */
    x: number
    /** Width of the slot the violin sits in. */
    width: number
    centerX: number
    /** The mirrored outline, ordered from the lowest value to the highest. `halfWidth` is the
     *  distance from `centerX` to either edge at that `y`. */
    outline: { y: number; halfWidth: number }[]
    medianY: number
    mean: { x: number; y: number }
    /** One marker per observation, jittered sideways so they do not overlap. */
    points: { x: number; y: number }[]
    dataIndex: number
}
