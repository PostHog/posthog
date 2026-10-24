// Types of `ReferenceLine`. Shared types it uses, declared in core.d.ts: .
// Generated from @posthog/quill-charts 0.3.0-beta.31, the version the canvas builder pins, by
// products/canvas/packages/canvas_builder/scripts/quill-charts-types.mjs. Do not edit.
// Importable from '@posthog/quill-charts': ReferenceLine, ReferenceLines, ReferenceLineProps, ReferenceLineOrientation, ReferenceLineLabelPosition, ReferenceLineStyle, ReferenceLineFillSide, ReferenceLineVariant, ReferenceLineStroke.
// Other declarations here are shapes to match, not names to import.

/** Dispatches to the orientation-specific renderer. Each sub-component does its own
 *  type narrowing, scale lookup, and bounds check, then hands pre-computed styles to
 *  {@link ReferenceLineView}. */
export declare function ReferenceLine(props: ReferenceLineProps): React.ReactElement | null

/** Renders a list of reference lines. */
export declare function ReferenceLines({ lines }: { lines: ReferenceLineProps[] }): React.ReactElement

export interface ReferenceLineProps {
    /** The axis value at which to draw the line. For horizontal lines this is a numeric
     *  y-value; for vertical lines it's an x-axis label (matching the chart's `labels`). */
    value: number | string
    /** `horizontal` draws across the plot at a y-value (default).
     *  `vertical` draws top-to-bottom at an x-axis label. */
    orientation?: ReferenceLineOrientation
    /** Optional text label rendered alongside the line. */
    label?: string
    /** Anchor the label at the `start` or `end` of the line. Defaults to `end`. */
    labelPosition?: ReferenceLineLabelPosition
    /** Style overrides. Variant picks sensible defaults; anything set here wins. */
    style?: ReferenceLineStyle
    /** Optional filled half-plane on one side of the line. */
    fillSide?: ReferenceLineFillSide
    /** Preset: `goal` (dashed grey), `alert` (dashed red), `marker` (solid thin grey). Defaults to `goal`. */
    variant?: ReferenceLineVariant
    /** Which y-axis this line references. Only used for horizontal lines. Defaults to the primary axis. */
    yAxisId?: string
    /** Reveal the numeric value in the label bubble when the line or its label is hovered. Defaults to
     *  true. `false` also drops the invisible hover target, so the line is inert to the pointer. Vertical
     *  (label-positioned) lines never reveal a value. */
    showValueOnHover?: boolean
    /** Chart axis orientation. When `'horizontal'`, a `'horizontal'`-orientation reference
     *  line at a numeric value is drawn as a vertical stripe at `scales.y(value)` — matching
     *  the value axis of horizontal bar charts. Defaults to the chart's own axis orientation
     *  (from context), so it's correct without the caller having to thread it through. */
    axisOrientation?: ReferenceLineOrientation
}

export type ReferenceLineOrientation = 'horizontal' | 'vertical'

export type ReferenceLineLabelPosition = 'start' | 'end'

export interface ReferenceLineStyle {
    /** CSS color string. Supports `var(--my-color)`. Overrides the variant default. */
    color?: string
    /** Stroke style. Defaults to the variant default. */
    stroke?: ReferenceLineStroke
    /** Line thickness in px. Defaults to the variant default. */
    width?: number
    /** CSS color used for the filled half-plane when `fillSide` is set. Defaults to `color`. */
    fillColor?: string
    /** Opacity 0-1 for the filled half-plane. Defaults to 0.1. */
    fillOpacity?: number
}

export type ReferenceLineFillSide = 'above' | 'below' | 'left' | 'right'

export type ReferenceLineVariant = 'goal' | 'alert' | 'marker'

export type ReferenceLineStroke = 'dashed' | 'solid'
