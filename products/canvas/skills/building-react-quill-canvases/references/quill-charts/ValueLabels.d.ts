// Types of `ValueLabels`. Shared types it uses, declared in core.d.ts: ValueLabelsProps, ValueLabelFormatter, ValueLabelsMode, ValueLabelContext.
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': ValueLabels.
// Other declarations here are shapes to match, not names to import.

export declare function ValueLabels({
    valueFormatter,
    minGap,
    mode,
    position,
    offset,
    background,
    fontSize,
    rotation,
}: ValueLabelsProps): React.ReactElement | null
