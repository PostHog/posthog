// Stateless canvas drawing primitives for PieChart.
//
// Pie charts work in polar coordinates and don't share the axis-based DrawContext
// used by line/bar/area renderers in core/canvas-renderer.ts. Keeping these
// primitives next to the chart type avoids polluting the shared module with
// shapes that no other chart can reuse.

import * as d3 from 'd3'

import type { PieLayout, ResolvedPieSlice, SliceAngle } from './pie-layout'
import { sliceHoverOffset, sliceLabelPosition } from './pie-layout'

interface DrawPieSlicesOptions {
    /** Index of the hovered slice, or -1. */
    hoverIndex: number
    /** Pixels to pop a hovered slice out along its bisector. 0 disables the effect. */
    hoverOffset: number
    /** Radians of gap between adjacent slices. */
    slicePadding: number
}

export function drawPieSlices(
    ctx: CanvasRenderingContext2D,
    layout: PieLayout,
    slices: ResolvedPieSlice[],
    angles: SliceAngle[],
    options: DrawPieSlicesOptions
): void {
    const { hoverIndex, hoverOffset, slicePadding } = options
    if (layout.outerRadius <= 0) {
        return
    }

    for (const angle of angles) {
        const slice = slices[angle.sliceIndex]
        const isHovered = angle.sliceIndex === hoverIndex
        const { dx, dy } = sliceHoverOffset(angle, isHovered, hoverOffset)

        // Symmetric padding eats from both sides of the slice; skip when the slice
        // is too narrow to survive the trim — drawing a negative arc paints a full circle.
        const padHalf = slicePadding / 2
        const start = angle.startAngle + padHalf
        const end = angle.endAngle - padHalf
        if (end <= start) {
            continue
        }

        const cx = layout.cx + dx
        const cy = layout.cy + dy

        ctx.beginPath()
        if (layout.innerRadius > 0) {
            ctx.arc(cx, cy, layout.outerRadius, start, end)
            ctx.arc(cx, cy, layout.innerRadius, end, start, true)
        } else {
            ctx.moveTo(cx, cy)
            ctx.arc(cx, cy, layout.outerRadius, start, end)
        }
        ctx.closePath()

        ctx.fillStyle = slice.color
        ctx.fill()
    }
}

interface DrawSliceLabelsOptions {
    /** Skip the label when the slice covers less than this fraction (0–1) of the pie. */
    minFraction: number
    /** Text mode: numeric value (formatted) or the slice label. */
    mode: 'value' | 'label'
    /** Formats numeric slice values. */
    valueFormatter: (value: number) => string
    /** Index of the hovered slice; that slice's label is drawn at the popped-out position. */
    hoverIndex: number
    /** Same hover-offset used by drawPieSlices, so labels track the popped-out slice. */
    hoverOffset: number
}

export function drawSliceLabels(
    ctx: CanvasRenderingContext2D,
    layout: PieLayout,
    slices: ResolvedPieSlice[],
    angles: SliceAngle[],
    options: DrawSliceLabelsOptions
): void {
    if (layout.outerRadius <= 0) {
        return
    }
    const { minFraction, mode, valueFormatter, hoverIndex, hoverOffset } = options

    ctx.save()
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.font = '500 12px var(--font-sans, system-ui, -apple-system, sans-serif)'

    for (const angle of angles) {
        if (angle.fraction < minFraction) {
            continue
        }
        const slice = slices[angle.sliceIndex]
        const text = mode === 'label' ? slice.label : valueFormatter(slice.value)
        if (!text) {
            continue
        }

        const isHovered = angle.sliceIndex === hoverIndex
        const { dx, dy } = sliceHoverOffset(angle, isHovered, hoverOffset)
        const pos = sliceLabelPosition(layout, angle)
        const x = pos.x + dx
        const y = pos.y + dy

        // Pill: filled with the slice color, white text, white border, rounded corners.
        const metrics = ctx.measureText(text)
        const paddingX = 8
        const paddingY = 4
        const w = metrics.width + paddingX * 2
        const h = 12 + paddingY * 2

        ctx.fillStyle = slice.color
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 2
        roundedRect(ctx, x - w / 2, y - h / 2, w, h, 25)
        ctx.fill()
        ctx.stroke()

        ctx.fillStyle = '#ffffff'
        ctx.fillText(text, x, y)
    }
    ctx.restore()
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, radius: number): void {
    const r = Math.min(radius, w / 2, h / 2)
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.lineTo(x + w - r, y)
    ctx.quadraticCurveTo(x + w, y, x + w, y + r)
    ctx.lineTo(x + w, y + h - r)
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
    ctx.lineTo(x + r, y + h)
    ctx.quadraticCurveTo(x, y + h, x, y + h - r)
    ctx.lineTo(x, y + r)
    ctx.quadraticCurveTo(x, y, x + r, y)
    ctx.closePath()
}

/** Darken the slice color a touch — same idiom BarChart uses for its hover highlight. */
export function highlightColorFor(color: string): string {
    return d3.color(color)?.darker(0.4).toString() ?? color
}
