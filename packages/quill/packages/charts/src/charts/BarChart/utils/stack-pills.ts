import { type BarRect, type BarRoundedCorners } from '../../../core/canvas-renderer'

const ALL_CORNERS: BarRoundedCorners = { topLeft: true, topRight: true, bottomLeft: true, bottomRight: true }

/** One fully-rounded rect per band, spanning the union of that band's stacked segments — the
 *  pill the bar layer is clipped to for `roundStackEnds`. Bars in the same band share a band-axis
 *  slot (same `dataIndex`), so we group by it and extend along the value axis. */
export function stackPillRects(bars: BarRect[], isHorizontal: boolean): BarRect[] {
    const byBand = new Map<number, BarRect>()
    for (const bar of bars) {
        if (bar.width <= 0 || bar.height <= 0) {
            continue
        }
        const existing = byBand.get(bar.dataIndex)
        if (!existing) {
            byBand.set(bar.dataIndex, { ...bar, corners: ALL_CORNERS })
            continue
        }
        if (isHorizontal) {
            const left = Math.min(existing.x, bar.x)
            const right = Math.max(existing.x + existing.width, bar.x + bar.width)
            existing.x = left
            existing.width = right - left
        } else {
            const top = Math.min(existing.y, bar.y)
            const bottom = Math.max(existing.y + existing.height, bar.y + bar.height)
            existing.y = top
            existing.height = bottom - top
        }
    }
    return [...byBand.values()]
}
