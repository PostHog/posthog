// Cached offscreen canvas — createElement+getContext is slow, measureText is fast.
// Callers must set ctx.font themselves before measuring.

export const FONT_FAMILY =
    '-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'

export const AXIS_LABEL_FONT = `12px ${FONT_FAMILY}`

export const ELLIPSIS = '…'

/** Largest pixel width a category (breakdown) tick label may occupy before it's truncated
 *  with an ellipsis. Without this, long breakdown values — most notably URLs — grow the axis
 *  margin to fit the widest label and push the plot off screen. */
export const MAX_CATEGORY_LABEL_WIDTH = 160

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

/** Truncate `text` with a trailing ellipsis so its rendered width fits within `maxWidth`.
 *  Returns the original string when it already fits, or when `maxWidth` is non-positive. */
export function truncateToWidth(text: string, maxWidth: number, font: string = AXIS_LABEL_FONT): string {
    if (maxWidth <= 0 || measureLabelWidth(text, font) <= maxWidth) {
        return text
    }
    if (measureLabelWidth(ELLIPSIS, font) >= maxWidth) {
        return ELLIPSIS
    }
    let low = 0
    let high = text.length
    while (low < high) {
        const mid = Math.ceil((low + high) / 2)
        const candidate = `${text.slice(0, mid).trimEnd()}${ELLIPSIS}`
        if (measureLabelWidth(candidate, font) <= maxWidth) {
            low = mid
        } else {
            high = mid - 1
        }
    }
    return `${text.slice(0, low).trimEnd()}${ELLIPSIS}`
}
