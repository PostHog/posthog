import { type SizeRect, syncCanvasSize } from '../canvas-size'
import type { ChartDimensions } from '../types'

// About 8 MB of RGBA per canvas. A larger budget gave no visible gain on dashboard charts at 3x zoom.
const MAX_ZOOMED_CANVAS_PIXELS = 2_000_000

/** Canvases in the viewport. Only these get zoom resolution, so zoom memory follows the charts in view. */
export const onScreenCanvases = new WeakSet<HTMLCanvasElement>()

/** Backing pixels per CSS pixel. Pinch-zoom changes `visualViewport.scale` and not `devicePixelRatio`.
 *  The browser re-rasterises text at the zoomed scale but magnifies a canvas bitmap, so an on-screen
 *  chart takes `devicePixelRatio × zoom`, up to a pixel budget. */
export function canvasRasterScale(rect: SizeRect, canvas: HTMLCanvasElement): number {
    const dpr = window.devicePixelRatio || 1
    if (!onScreenCanvases.has(canvas)) {
        return dpr
    }
    const zoom = Math.max(1, window.visualViewport?.scale ?? 1)
    const area = rect.width * rect.height
    const budget = area > 0 ? Math.sqrt(MAX_ZOOMED_CANVAS_PIXELS / area) : dpr
    return Math.max(dpr, Math.min(dpr * zoom, budget))
}

/** Size the backing store to `dimensions`, reset the transform to the raster scale, and clear
 *  the whole canvas, leaving the ctx in a saved state the caller restores after drawing. Shared by
 *  the static and hover draw loops.
 *
 *  The resize happens here, in the same frame as the repaint, because a resize wipes the bitmap.
 *  Until the draw loop runs, the canvas keeps showing the last frame.
 *
 *  The scale is derived from the backing store (`canvas.width / dimensions.width`, and the same
 *  for height), so the transform always matches the rounded integer size the canvas actually has.
 *  Each axis gets its own ratio: `syncCanvasSize` rounds each side, and on a capped tall canvas
 *  one shared ratio drifts the far rows by tens of pixels. */
export function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): void {
    const fallback = canvasRasterScale(dimensions, ctx.canvas)
    syncCanvasSize(ctx.canvas, dimensions, fallback)
    const scaleX = dimensions.width > 0 ? ctx.canvas.width / dimensions.width : fallback
    const scaleY = dimensions.height > 0 ? ctx.canvas.height / dimensions.height : fallback
    ctx.save()
    ctx.setTransform(scaleX, 0, 0, scaleY, 0, 0)
    ctx.clearRect(0, 0, dimensions.width, dimensions.height)
}

/** Free the backing store of a canvas that has nothing to show. A 0×0 canvas holds no bitmap and
 *  gets no compositor layer, so idle hover overlays cost nothing. `clearAndPrepare` sizes it again
 *  on the next draw. */
export function releaseCanvas(canvas: HTMLCanvasElement): void {
    if (canvas.width !== 0) {
        canvas.width = 0
    }
    if (canvas.height !== 0) {
        canvas.height = 0
    }
}
