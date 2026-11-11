import type { ViolinRect } from './types'

/** Half-length of the median tick, as a share of the slot width. */
const MEDIAN_HALF_WIDTH_RATIO = 0.18
const OUTLINE_WIDTH = 1
const MEDIAN_WIDTH = 3
const POINT_RADIUS = 2.5
const MEAN_RADIUS = 3.5

export interface DrawViolinsOptions {
    /** Outline color, and the stroke of the mean marker. */
    color: string
    fillColor: string
    medianColor: string
    pointFillColor: string
    pointStrokeColor: string
    meanFillColor: string
}

function traceOutline(ctx: CanvasRenderingContext2D, violin: ViolinRect): void {
    const { centerX, outline } = violin
    ctx.beginPath()
    outline.forEach((point, i) => {
        if (i === 0) {
            ctx.moveTo(centerX + point.halfWidth, point.y)
        } else {
            ctx.lineTo(centerX + point.halfWidth, point.y)
        }
    })
    for (let i = outline.length - 1; i >= 0; i--) {
        ctx.lineTo(centerX - outline[i].halfWidth, outline[i].y)
    }
    ctx.closePath()
}

/** Draws every violin: the filled outline, one marker per observation, the median tick, then the
 *  mean marker on top. Pure canvas drawing — the geometry is already in pixels. */
export function drawViolins(ctx: CanvasRenderingContext2D, violins: ViolinRect[], options: DrawViolinsOptions): void {
    if (violins.length === 0) {
        return
    }
    const { color, fillColor, medianColor, pointFillColor, pointStrokeColor, meanFillColor } = options

    ctx.save()
    ctx.setLineDash([])
    ctx.lineWidth = OUTLINE_WIDTH
    ctx.fillStyle = fillColor
    ctx.strokeStyle = color
    for (const violin of violins) {
        traceOutline(ctx, violin)
        ctx.fill()
        ctx.stroke()
    }

    ctx.fillStyle = pointFillColor
    ctx.strokeStyle = pointStrokeColor
    ctx.lineWidth = OUTLINE_WIDTH
    for (const violin of violins) {
        for (const point of violin.points) {
            ctx.beginPath()
            ctx.arc(point.x, point.y, POINT_RADIUS, 0, Math.PI * 2)
            ctx.fill()
            ctx.stroke()
        }
    }

    ctx.strokeStyle = medianColor
    ctx.lineWidth = MEDIAN_WIDTH
    ctx.beginPath()
    for (const violin of violins) {
        const halfWidth = violin.width * MEDIAN_HALF_WIDTH_RATIO
        ctx.moveTo(violin.centerX - halfWidth, violin.medianY)
        ctx.lineTo(violin.centerX + halfWidth, violin.medianY)
    }
    ctx.stroke()

    ctx.fillStyle = meanFillColor
    ctx.strokeStyle = color
    ctx.lineWidth = OUTLINE_WIDTH * 1.5
    for (const violin of violins) {
        ctx.beginPath()
        ctx.arc(violin.mean.x, violin.mean.y, MEAN_RADIUS, 0, Math.PI * 2)
        ctx.fill()
        ctx.stroke()
    }
    ctx.restore()
}

/** Tints the violin under the cursor. Drawn on the hover canvas, over the static layer. */
export function drawViolinHighlight(ctx: CanvasRenderingContext2D, violin: ViolinRect, color: string): void {
    ctx.save()
    traceOutline(ctx, violin)
    ctx.fillStyle = color
    ctx.fill()
    ctx.restore()
}
