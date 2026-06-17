import type { ChartDimensions } from '../types'
import { effectiveCanvasScale } from './canvasScale'

/**
 * Reset the transform to the (clamped) device-pixel scale and clear the whole canvas, leaving the
 * ctx in a saved state the caller restores after drawing. Shared by the static and hover draw
 * loops. The scale matches the backing store `sizeCanvas` allocated, so it stays within the
 * browser's max canvas size.
 *
 * Returns `false` if the context is unusable (the canvas is in an error state — e.g. a prior
 * oversized allocation failed). Callers must skip drawing and the trailing `ctx.restore()` when
 * this returns `false`, so a poisoned canvas doesn't throw on every animation frame.
 */
export function clearAndPrepare(ctx: CanvasRenderingContext2D, dimensions: ChartDimensions): boolean {
    const dpr = window.devicePixelRatio || 1
    const scale = effectiveCanvasScale(dimensions.width, dimensions.height, dpr)
    let saved = false
    try {
        ctx.save()
        saved = true
        ctx.setTransform(scale, 0, 0, scale, 0, 0)
        ctx.clearRect(0, 0, dimensions.width, dimensions.height)
        return true
    } catch {
        // Canvas entered an error state. Unwind the save we made so the ctx stack stays balanced,
        // and tell the caller to skip this frame's draw.
        if (saved) {
            try {
                ctx.restore()
            } catch {
                // Nothing more we can do with a poisoned canvas.
            }
        }
        return false
    }
}
