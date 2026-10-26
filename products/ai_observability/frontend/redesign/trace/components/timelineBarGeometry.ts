// Keeps instant events visible as a sliver instead of a zero-width bar.
export const MIN_BAR_PERCENT = 1.5

export interface TimelineBarGeometry {
    leftPercent: number
    widthPercent: number
}

export function timelineBarGeometry(startMs: number, durationMs: number, totalMs: number): TimelineBarGeometry {
    const safeTotal = totalMs > 0 ? totalMs : 1
    const leftPercent = Math.min((startMs / safeTotal) * 100, 100 - MIN_BAR_PERCENT)
    const widthPercent = Math.min(Math.max((durationMs / safeTotal) * 100, MIN_BAR_PERCENT), 100 - leftPercent)
    return { leftPercent, widthPercent }
}
