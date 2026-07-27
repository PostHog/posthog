import type { ResolvedSeries } from './types'

export interface PieSlice<Meta = unknown> {
    /** Index into the *original* (pre-exclusion) series array. */
    seriesIndex: number
    series: ResolvedSeries<Meta>
    /** Absolute slice magnitude. Negative inputs are clamped to 0 — a pie can't render them. */
    value: number
    /** value / total (0 when total is 0). */
    fraction: number
    /** Radians, 12 o'clock = 0, increasing clockwise (d3.pie convention). */
    startAngle: number
    endAngle: number
    /** Bisector angle — anchor for pop-out and on-slice labels. */
    centroidAngle: number
    color: string
}

export interface PieLayout<Meta = unknown> {
    slices: PieSlice<Meta>[]
    total: number
    cx: number
    cy: number
    /** Outer slice radius, *excluding* hover pop-out room. */
    outerRadius: number
    /** Inner radius (0 for pie, > 0 for donut). */
    innerRadius: number
    /** Radians gap between adjacent slices. */
    padAngle: number
}

/** Maps a cursor offset (dx, dy) from the chart center to an angle in radians, matching
 *  the d3.pie convention: 12 o'clock = 0, increasing clockwise, range [0, 2π). */
export function cursorOffsetToAngle(dx: number, dy: number): number {
    // 12 o'clock = (0, -1) → atan2(0, 1) = 0
    // 3 o'clock = (1, 0) → atan2(1, 0) = π/2
    // 6 o'clock = (0, 1) → atan2(0, -1) = π
    // 9 o'clock = (-1, 0) → atan2(-1, 0) = -π/2 → normalized to 3π/2
    let a = Math.atan2(dx, -dy)
    if (a < 0) {
        a += 2 * Math.PI
    }
    return a
}

export interface SliceAtOptions {
    /** Allowance beyond `outerRadius` so the popped-out slice still registers as hovered. */
    outerSlack?: number
}

/** Returns the index of the slice under the cursor, or -1.
 *  - Misses the donut inner hole (`r < innerRadius`).
 *  - Misses past the outer edge plus optional slack.
 *  - Treats `padAngle/2` of each slice's start/end as a gap (no hit).
 *  - Handles d3.pie's 12 o'clock wraparound (slice that crosses 0). */
export function sliceAt<Meta>(
    layout: PieLayout<Meta>,
    cursor: { x: number; y: number },
    { outerSlack = 0 }: SliceAtOptions = {}
): number {
    if (layout.slices.length === 0) {
        return -1
    }
    const dx = cursor.x - layout.cx
    const dy = cursor.y - layout.cy
    const r = Math.hypot(dx, dy)
    if (r < layout.innerRadius || r > layout.outerRadius + outerSlack) {
        return -1
    }
    const a = cursorOffsetToAngle(dx, dy)
    const halfPad = layout.padAngle / 2
    for (let i = 0; i < layout.slices.length; i++) {
        const s = layout.slices[i]
        let start = s.startAngle + halfPad
        let end = s.endAngle - halfPad
        if (start >= end) {
            continue
        }
        if (start < 0 || end > 2 * Math.PI) {
            // Wraparound — slice crosses 12 o'clock. Split into the [start, 2π) ∪ [0, end mod 2π) check.
            const sNorm = ((start % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)
            const eNorm = ((end % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)
            if (a >= sNorm || a < eNorm) {
                return i
            }
            continue
        }
        if (a >= start && a < end) {
            return i
        }
    }
    return -1
}
