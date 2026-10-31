// Types of `AxisTitles`. Shared types it uses, declared in core.d.ts: .
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': AxisTitles, AxisTitlesProps.
// Other declarations here are shapes to match, not names to import.

export declare function AxisTitles({
    xAxisLabel,
    yAxisLabel,
    hideXAxis,
    hideYAxis,
    orientation,
    axisColor,
}: AxisTitlesProps): React.ReactElement | null

export interface AxisTitlesProps {
    xAxisLabel?: string
    /** Category-axis title for horizontal charts only; vertical titles come per-gutter. */
    yAxisLabel?: string
    hideXAxis?: boolean
    hideYAxis?: boolean
    orientation?: 'vertical' | 'horizontal'
    axisColor: string
}
