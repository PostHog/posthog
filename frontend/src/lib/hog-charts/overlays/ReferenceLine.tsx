/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from d3 scales */
import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'

export type ReferenceLineOrientation = 'horizontal' | 'vertical'
export type ReferenceLineVariant = 'goal' | 'alert' | 'marker'
export type ReferenceLineFillSide = 'above' | 'below' | 'left' | 'right'
export type ReferenceLineLabelPosition = 'start' | 'end'
export type ReferenceLineStroke = 'dashed' | 'solid'

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
    /** Chart axis orientation. When `'horizontal'`, a `'horizontal'`-orientation reference
     *  line at a numeric value is drawn as a vertical stripe at `scales.y(value)` — matching
     *  the value axis of horizontal bar charts. Defaults to `'vertical'`. */
    axisOrientation?: ReferenceLineOrientation
}

interface ResolvedStyle {
    color: string
    stroke: ReferenceLineStroke
    width: number
}

const VARIANT_DEFAULTS: Record<ReferenceLineVariant, ResolvedStyle> = {
    goal: { color: 'rgba(0, 0, 0, 0.4)', stroke: 'dashed', width: 2 },
    alert: { color: 'var(--danger)', stroke: 'dashed', width: 2 },
    marker: { color: 'rgba(0, 0, 0, 0.5)', stroke: 'solid', width: 1 },
}

/** Vertical distance from the line to the top edge of the text label. */
const LABEL_OFFSET = 18
/** Padding between the label and the plot edge. */
const LABEL_PADDING = 4

function resolveStyle(variant: ReferenceLineVariant, style: ReferenceLineStyle | undefined): ResolvedStyle {
    const defaults = VARIANT_DEFAULTS[variant]
    return {
        color: style?.color ?? defaults.color,
        stroke: style?.stroke ?? defaults.stroke,
        width: style?.width ?? defaults.width,
    }
}

/** Renders a list of reference lines. */
export function ReferenceLines({ lines }: { lines: ReferenceLineProps[] }): React.ReactElement {
    return (
        <>
            {lines.map((props, i) => (
                <ReferenceLine key={`${i}-${props.value}-${props.label ?? ''}`} {...props} />
            ))}
        </>
    )
}

/** Dispatches to the orientation-specific renderer. Each sub-component does its own
 *  type narrowing, scale lookup, and bounds check, then hands pre-computed styles to
 *  {@link ReferenceLineView}. */
export function ReferenceLine(props: ReferenceLineProps): React.ReactElement | null {
    const { orientation = 'horizontal', variant = 'goal', style, axisOrientation = 'vertical' } = props
    const resolved = useMemo(
        () => resolveStyle(variant, style),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [variant, style?.color, style?.stroke, style?.width]
    )

    const common: ResolvedProps = {
        resolved,
        fillSide: props.fillSide,
        fillColor: style?.fillColor ?? resolved.color,
        fillOpacity: style?.fillOpacity ?? 0.1,
        label: props.label,
        labelPosition: props.labelPosition ?? 'end',
    }

    if (orientation === 'horizontal') {
        if (typeof props.value !== 'number') {
            return null
        }
        if (axisOrientation === 'horizontal') {
            return <HorizontalAxisValueReferenceLine value={props.value} {...common} />
        }
        return <HorizontalReferenceLine y={props.value} yAxisId={props.yAxisId} {...common} />
    }
    return typeof props.value === 'string' ? <VerticalReferenceLine xLabel={props.value} {...common} /> : null
}

interface ResolvedProps {
    resolved: ResolvedStyle
    fillSide: ReferenceLineFillSide | undefined
    fillColor: string
    fillOpacity: number
    label: string | undefined
    labelPosition: ReferenceLineLabelPosition
}

function HorizontalReferenceLine({
    y: value,
    yAxisId,
    resolved,
    fillSide,
    fillColor,
    fillOpacity,
    label,
    labelPosition,
}: ResolvedProps & { y: number; yAxisId?: string }): React.ReactElement | null {
    const { scales, dimensions } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight, width: containerWidth } = dimensions
    const plotRight = plotLeft + plotWidth
    const plotBottom = plotTop + plotHeight

    const yScaleFn = yAxisId && scales.yAxes?.[yAxisId] ? scales.yAxes[yAxisId].scale : scales.y
    const y = yScaleFn(value)
    if (!isFinite(y) || y < plotTop || y > plotBottom) {
        return null
    }

    const lineStyle: React.CSSProperties = {
        left: plotLeft,
        top: y - resolved.width / 2,
        width: plotWidth,
        height: 0,
        borderTopWidth: resolved.width,
        borderTopStyle: resolved.stroke,
        borderTopColor: resolved.color,
    }
    const labelStyle: React.CSSProperties = {
        top: y - LABEL_OFFSET,
        ...(labelPosition === 'end'
            ? { right: containerWidth - plotRight + LABEL_PADDING }
            : { left: plotLeft + LABEL_PADDING }),
        color: resolved.color,
    }

    let fillRect: React.CSSProperties | null = null
    if (fillSide === 'above') {
        fillRect = { left: plotLeft, top: plotTop, width: plotWidth, height: y - plotTop }
    } else if (fillSide === 'below') {
        fillRect = { left: plotLeft, top: y, width: plotWidth, height: plotBottom - y }
    }

    return (
        <ReferenceLineView
            fillRect={fillRect}
            fillColor={fillColor}
            fillOpacity={fillOpacity}
            lineStyle={lineStyle}
            label={label}
            labelStyle={labelStyle}
        />
    )
}

// Renders a vertical stripe at a resolved x-pixel — used by both the categorical-x
// reference line (string xLabel) and the horizontal-axis-chart numeric variant
// (scales.y(value) returns an x-pixel in horizontal bar charts).
//
// `fillBefore` / `fillAfter` are direction-neutral: callers translate their own
// fillSide enum into these so we don't have to know whether the half-plane is
// "left/right" (categorical) or "below/above value threshold" (horizontal-axis).
function VerticalStripe({
    x,
    resolved,
    fillBefore,
    fillAfter,
    fillColor,
    fillOpacity,
    label,
    labelPosition,
}: Omit<ResolvedProps, 'fillSide'> & {
    x: number
    fillBefore: boolean
    fillAfter: boolean
}): React.ReactElement | null {
    const { dimensions } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight, height: containerHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const plotBottom = plotTop + plotHeight

    if (!isFinite(x) || x < plotLeft || x > plotRight) {
        return null
    }

    const lineStyle: React.CSSProperties = {
        left: x - resolved.width / 2,
        top: plotTop,
        width: 0,
        height: plotHeight,
        borderLeftWidth: resolved.width,
        borderLeftStyle: resolved.stroke,
        borderLeftColor: resolved.color,
    }
    const labelStyle: React.CSSProperties = {
        left: x + LABEL_PADDING,
        ...(labelPosition === 'end'
            ? { bottom: containerHeight - plotBottom + LABEL_PADDING }
            : { top: plotTop + LABEL_PADDING }),
        color: resolved.color,
    }

    let fillRect: React.CSSProperties | null = null
    if (fillBefore) {
        fillRect = { left: plotLeft, top: plotTop, width: x - plotLeft, height: plotHeight }
    } else if (fillAfter) {
        fillRect = { left: x, top: plotTop, width: plotRight - x, height: plotHeight }
    }

    return (
        <ReferenceLineView
            fillRect={fillRect}
            fillColor={fillColor}
            fillOpacity={fillOpacity}
            lineStyle={lineStyle}
            label={label}
            labelStyle={labelStyle}
        />
    )
}

function VerticalReferenceLine({
    xLabel,
    fillSide,
    ...rest
}: ResolvedProps & { xLabel: string }): React.ReactElement | null {
    const { scales } = useChartLayout()
    const x = scales.x(xLabel)
    if (x == null) {
        return null
    }
    return <VerticalStripe x={x} fillBefore={fillSide === 'left'} fillAfter={fillSide === 'right'} {...rest} />
}

// Horizontal-axis chart variant: numeric value, mapped through scales.y because
// in horizontal bar charts scales.y is the value scale producing x-pixels.
// `'above'` (value above the threshold) → right half-plane, `'below'` → left.
function HorizontalAxisValueReferenceLine({
    value,
    fillSide,
    ...rest
}: ResolvedProps & { value: number }): React.ReactElement | null {
    const { scales } = useChartLayout()
    return (
        <VerticalStripe
            x={scales.y(value)}
            fillBefore={fillSide === 'below'}
            fillAfter={fillSide === 'above'}
            {...rest}
        />
    )
}

/** The shared shell: optional filled half-plane, the stroked line, and an optional label.
 *  Sub-components compute the pixel geometry; this just paints it. */
function ReferenceLineView({
    fillRect,
    fillColor,
    fillOpacity,
    lineStyle,
    label,
    labelStyle,
}: {
    fillRect: React.CSSProperties | null
    fillColor: string
    fillOpacity: number
    lineStyle: React.CSSProperties
    label: string | undefined
    labelStyle: React.CSSProperties
}): React.ReactElement {
    return (
        <>
            {fillRect && (
                <div
                    className="absolute pointer-events-none"
                    style={{ ...fillRect, backgroundColor: fillColor, opacity: fillOpacity }}
                />
            )}
            <div data-attr="hog-chart-reference-line" className="absolute pointer-events-none" style={lineStyle} />
            {label && (
                <div
                    data-attr="hog-chart-reference-line-label"
                    className="absolute pointer-events-none whitespace-nowrap font-medium text-[11px]"
                    style={labelStyle}
                >
                    {label}
                </div>
            )}
        </>
    )
}
