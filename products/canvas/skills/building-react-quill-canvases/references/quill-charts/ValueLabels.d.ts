// Types of `ValueLabels`. Shared types it uses, declared in core.d.ts: ValueLabelFormatter, ValueLabelContext.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': ValueLabels, ValueLabelsProps.
// Other declarations here are shapes to match, not names to import.

export declare function ValueLabels({
    valueFormatter,
    minGap,
    mode,
    position,
    offset,
}: ValueLabelsProps): React.ReactElement | null

export interface ValueLabelsProps {
    valueFormatter?: ValueLabelFormatter
    minGap?: number
    mode?: ValueLabelsMode
    /** Per-segment labels only: place labels at the bar end (default) or inside the segment's center. */
    position?: 'end' | 'center'
    /** Gap in px between the bar tip and the label, applied along the value axis in the outward
     *  direction (right/above the tip, or inward for labels flipped inside a clipped bar). Ignored
     *  for centered (`percent`) labels. Defaults to 0 — the label's edge sits on the bar tip. */
    offset?: number
}

export type ValueLabelsMode = 'per-segment' | 'stack-total'
