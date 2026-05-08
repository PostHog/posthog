/** Shared offscreen canvas context used by overlays and the margin estimator to measure
 *  label widths. The context is created lazily on first use and cached for the lifetime
 *  of the page — `measureText` is fast but `createElement('canvas').getContext('2d')`
 *  is not.
 *
 *  Callers must set `ctx.font` themselves before measuring. */

export const LABEL_FONT =
    '12px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'

let measureCtx: CanvasRenderingContext2D | null = null
export function getTextMeasureCtx(): CanvasRenderingContext2D | null {
    if (!measureCtx) {
        measureCtx = document.createElement('canvas').getContext('2d')
    }
    return measureCtx
}

/** Measure a single label using the default chart font. Falls back to a coarse
 *  per-character estimate when the canvas context is unavailable (e.g. SSR). */
export function measureLabelWidth(text: string, font: string = LABEL_FONT): number {
    const ctx = getTextMeasureCtx()
    if (!ctx) {
        return text.length * 7
    }
    ctx.font = font
    return ctx.measureText(text).width
}
