import { roundCapInset, targetTickSize } from './gauge-layout'
import type { GaugeLayout } from './gauge-layout'

export interface GaugePaintBand {
    startAngle: number
    endAngle: number
    color: string
}

export interface GaugePaint {
    layout: GaugeLayout
    trackColor: string
    bands: GaugePaintBand[]
    /** Angle the value arc ends at, or null for an empty arc. */
    valueAngle: number | null
    valueColor: string
    /** Angle of the target tick, or null when there is no target in range. */
    targetAngle: number | null
    targetColor: string
}

const FULL_TURN = 2 * Math.PI
// Gap between adjacent threshold bands, in px along the ring.
const BAND_GAP_PX = 1.5

function isFullCircle(layout: GaugeLayout): boolean {
    return layout.angles.sweep >= FULL_TURN - 1e-9
}

/** Stroke a round-capped arc whose caps land exactly on `from` and `to`. An arc shorter than its
 *  caps paints a dot at `from`, so a small nonzero value stays visible. */
function strokeRoundArc(
    ctx: CanvasRenderingContext2D,
    layout: GaugeLayout,
    from: number,
    to: number,
    color: string
): void {
    const { cx, cy, radius, thickness } = layout
    if (thickness <= 0 || radius <= 0) {
        return
    }
    if (isFullCircle(layout) && to - from >= FULL_TURN - 1e-9) {
        ctx.beginPath()
        ctx.lineCap = 'butt'
        ctx.lineWidth = thickness
        ctx.strokeStyle = color
        ctx.arc(cx, cy, radius, 0, FULL_TURN)
        ctx.stroke()
        return
    }
    const inset = roundCapInset(radius, thickness)
    const start = from + inset
    const end = Math.max(start, to - inset)
    ctx.beginPath()
    ctx.lineCap = 'round'
    ctx.lineWidth = thickness
    ctx.strokeStyle = color
    ctx.arc(cx, cy, radius, start, end)
    ctx.stroke()
}

function drawBands(ctx: CanvasRenderingContext2D, layout: GaugeLayout, bands: GaugePaintBand[]): void {
    const { cx, cy, bandRadius, bandThickness, angles } = layout
    if (bandThickness <= 0 || bands.length === 0) {
        return
    }
    const halfGap = BAND_GAP_PX / 2 / bandRadius
    ctx.lineCap = 'butt'
    ctx.lineWidth = bandThickness
    for (const band of bands) {
        // Only the joins between bands get a gap. The outer ends line up with the track ends.
        const start = band.startAngle > angles.start + 1e-9 ? band.startAngle + halfGap : band.startAngle
        const end = band.endAngle < angles.end - 1e-9 ? band.endAngle - halfGap : band.endAngle
        if (end <= start) {
            continue
        }
        ctx.beginPath()
        ctx.strokeStyle = band.color
        ctx.arc(cx, cy, bandRadius, start, end)
        ctx.stroke()
    }
}

function drawTarget(ctx: CanvasRenderingContext2D, paint: GaugePaint, angle: number): void {
    const { cx, cy, innerRadius, outerRadius, thickness } = paint.layout
    const { overhang, width, gap } = targetTickSize(thickness)
    const r0 = innerRadius - overhang
    const r1 = outerRadius + overhang
    const strokeTick = (): void => {
        ctx.beginPath()
        ctx.moveTo(cx + Math.cos(angle) * r0, cy + Math.sin(angle) * r0)
        ctx.lineTo(cx + Math.cos(angle) * r1, cy + Math.sin(angle) * r1)
        ctx.stroke()
    }
    ctx.lineCap = 'round'
    // Erasing a wider stroke first cuts a gap through the rings, so the tick reads over any arc color
    // and the gap shows whatever surface sits behind the transparent canvas.
    ctx.save()
    ctx.globalCompositeOperation = 'destination-out'
    ctx.lineWidth = width + 2 * gap
    strokeTick()
    ctx.restore()
    ctx.strokeStyle = paint.targetColor
    ctx.lineWidth = width
    strokeTick()
}

/** Paint the threshold bands, the track, the value arc, and the target tick, back to front. */
export function drawGauge(ctx: CanvasRenderingContext2D, paint: GaugePaint): void {
    const { layout } = paint
    drawBands(ctx, layout, paint.bands)
    strokeRoundArc(ctx, layout, layout.angles.start, layout.angles.end, paint.trackColor)
    if (paint.valueAngle !== null && paint.valueAngle > layout.angles.start) {
        strokeRoundArc(ctx, layout, layout.angles.start, paint.valueAngle, paint.valueColor)
    }
    if (paint.targetAngle !== null) {
        drawTarget(ctx, paint, paint.targetAngle)
    }
}
