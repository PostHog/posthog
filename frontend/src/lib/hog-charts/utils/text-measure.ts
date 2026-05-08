// Cached offscreen canvas — createElement+getContext is slow, measureText is fast.
// Callers must set ctx.font themselves before measuring.

export const AXIS_LABEL_FONT =
    '12px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'

let measureCtx: CanvasRenderingContext2D | null = null
export function getTextMeasureCtx(): CanvasRenderingContext2D | null {
    if (!measureCtx) {
        measureCtx = document.createElement('canvas').getContext('2d')
    }
    return measureCtx
}

/** Falls back to length × 7 when the canvas context is unavailable (SSR). */
export function measureLabelWidth(text: string, font: string = AXIS_LABEL_FONT): number {
    const ctx = getTextMeasureCtx()
    if (!ctx) {
        return text.length * 7
    }
    ctx.font = font
    return ctx.measureText(text).width
}
