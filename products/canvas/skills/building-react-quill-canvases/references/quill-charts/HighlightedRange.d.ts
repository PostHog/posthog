// Types of `HighlightedRange`. Shared types it uses, declared in core.d.ts: .
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': HighlightedRange, HighlightedRangeProps.
// Other declarations here are shapes to match, not names to import.

/** Translucent box spanning an x-axis label/index range — mirrors an external selection
 *  (e.g. the rows currently visible in a paired virtualized list) onto the chart. On band
 *  (bar) charts the box covers the full bands of both endpoints; on point (line) charts it
 *  runs from point to point. Composes as a chart child like {@link ReferenceLine}; renders
 *  null when an endpoint doesn't resolve to a positioned label. */
export declare function HighlightedRange({
    start,
    end,
    color,
    fillOpacity,
    borderOpacity,
}: HighlightedRangeProps): React.ReactElement | null

export interface HighlightedRangeProps {
    /** Start of the range — a data index (number) or an x-axis label (string). */
    start: number | string
    /** End of the range, inclusive — a data index (number) or an x-axis label (string). */
    end: number | string
    /** CSS color for the fill and border. Supports `var(--my-color)`. */
    color?: string
    /** Opacity 0-1 of the translucent fill. Defaults to 0.1. */
    fillOpacity?: number
    /** Opacity 0-1 of the 1px border marking the range edges. Defaults to 0.8. Pass 0 for no border. */
    borderOpacity?: number
}
