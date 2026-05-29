export interface PieRing {
    cx: number
    cy: number
    innerRadius: number
    outerRadius: number
    padAngle: number
}

/** d3.pie angle convention: 0 = 12 o'clock, increasing clockwise. */
export interface PieSliceArc {
    startAngle: number
    endAngle: number
    centroidAngle: number
    color: string
}

export interface DrawPieSliceShapeOptions {
    /** Pixels to shift the slice along its bisector — 0 for the static layer, > 0 for hover pop-out. */
    offset: number
    fillStyle: string
    /** Inter-slice stroke color (typically `theme.backgroundColor`). Omit to skip stroking. */
    withStroke: string | undefined
}

/** Lower-level slice painter — takes explicit fill / stroke so the hover layer can both
 *  mask (background fill, no stroke) and re-paint (slice color, with stroke) using the same
 *  arc geometry. Caller owns ctx state outside of fill / stroke / lineWidth. */
export function drawPieSliceShape(
    ctx: CanvasRenderingContext2D,
    ring: PieRing,
    slice: PieSliceArc,
    { offset, fillStyle, withStroke }: DrawPieSliceShapeOptions
): void {
    const halfPad = ring.padAngle / 2
    const start = slice.startAngle + halfPad
    const end = slice.endAngle - halfPad
    if (start >= end) {
        return
    }
    const offsetX = offset === 0 ? 0 : Math.sin(slice.centroidAngle) * offset
    const offsetY = offset === 0 ? 0 : -Math.cos(slice.centroidAngle) * offset
    const cx = ring.cx + offsetX
    const cy = ring.cy + offsetY

    // Canvas arc convention: 0 = 3 o'clock, increasing clockwise. d3.pie uses
    // 0 = 12 o'clock. Subtract π/2 to align.
    const cStart = start - Math.PI / 2
    const cEnd = end - Math.PI / 2

    ctx.fillStyle = fillStyle
    ctx.beginPath()
    if (ring.innerRadius > 0) {
        ctx.arc(cx, cy, ring.outerRadius, cStart, cEnd, false)
        ctx.arc(cx, cy, ring.innerRadius, cEnd, cStart, true)
    } else {
        ctx.moveTo(cx, cy)
        ctx.arc(cx, cy, ring.outerRadius, cStart, cEnd, false)
    }
    ctx.closePath()
    ctx.fill()

    if (withStroke) {
        ctx.lineWidth = 1
        ctx.strokeStyle = withStroke
        ctx.stroke()
    }
}

export interface DrawPieSlicesOptions {
    /** Slice index to omit — used by the hover layer, which draws the popped slice elsewhere.
     *  Defaults to -1 (paint every slice). */
    skipIndex?: number
    /** Per-slice offset along the bisector — typically 0 for the static layer. */
    offset: number
    /** Theme background color. Used as the inter-slice stroke when more than one slice is
     *  present; skipped for single-slice charts (no neighbour to separate from). */
    backgroundColor: string | undefined
}

/** Paints a whole ring of slices in one pass, filling each with its own color and stroking
 *  the inter-slice gap with the theme background (when applicable). */
export function drawPieSlices(
    ctx: CanvasRenderingContext2D,
    ring: PieRing,
    slices: PieSliceArc[],
    { skipIndex = -1, offset, backgroundColor }: DrawPieSlicesOptions
): void {
    const withStroke = slices.length > 1 ? backgroundColor : undefined
    for (let i = 0; i < slices.length; i++) {
        if (i === skipIndex) {
            continue
        }
        const slice = slices[i]
        drawPieSliceShape(ctx, ring, slice, { offset, fillStyle: slice.color, withStroke })
    }
}
