import type { ChartDimensions } from '../../../core/types'

/** Start at 12 o'clock and sweep clockwise — matches the SQL pie convention. */
export const DEFAULT_START_ANGLE = -Math.PI / 2

export interface ResolvedPieSlice {
    key: string
    label: string
    value: number
    color: string
}

export interface PieLayout {
    /** Centre of the pie in canvas pixels. */
    cx: number
    /** Centre of the pie in canvas pixels. */
    cy: number
    /** Outer radius in pixels. */
    outerRadius: number
    /** Inner (donut hole) radius in pixels. 0 for a full pie. */
    innerRadius: number
}

export interface SliceAngle {
    /** Index into the *filtered* (positive-value) slice array. */
    sliceIndex: number
    /** Start angle in radians. */
    startAngle: number
    /** End angle in radians. */
    endAngle: number
    /** Fraction of the total (0–1). */
    fraction: number
}

interface PieLayoutOptions {
    /** Donut hole, 0–1 fraction of outer radius. Defaults to 0. */
    innerRadius?: number
    /** Extra space reserved for hover-offset / value labels. Defaults to 16. */
    hoverOffset?: number
}

/** Compute the pie centre and radius from the available chart dimensions.
 *  Reserves `hoverOffset` pixels of breathing room so a popped-out slice
 *  doesn't get clipped by the canvas edge. */
export function computePieLayout(dimensions: ChartDimensions, options: PieLayoutOptions = {}): PieLayout {
    const { innerRadius = 0, hoverOffset = 16 } = options
    const cx = dimensions.plotLeft + dimensions.plotWidth / 2
    const cy = dimensions.plotTop + dimensions.plotHeight / 2
    const available = Math.min(dimensions.plotWidth, dimensions.plotHeight) / 2
    const outerRadius = Math.max(0, available - Math.max(0, hoverOffset))
    const clampedInner = Math.max(0, Math.min(1, innerRadius))
    return { cx, cy, outerRadius, innerRadius: outerRadius * clampedInner }
}

/** Compute the angular span of each slice. Filters happen at the caller —
 *  this function trusts the slices it receives. */
export function computeSliceAngles(
    slices: ResolvedPieSlice[],
    total: number,
    startAngle: number = DEFAULT_START_ANGLE
): SliceAngle[] {
    if (total <= 0 || slices.length === 0) {
        return []
    }
    const out: SliceAngle[] = []
    let cursor = startAngle
    for (let i = 0; i < slices.length; i++) {
        const fraction = slices[i].value / total
        const sweep = fraction * Math.PI * 2
        out.push({ sliceIndex: i, startAngle: cursor, endAngle: cursor + sweep, fraction })
        cursor += sweep
    }
    return out
}

/** Returns the index of the slice under the cursor, or -1.
 *  Cursor position is in canvas pixels (relative to the wrapper). */
export function hitTestSlice(
    cursorX: number,
    cursorY: number,
    layout: PieLayout,
    sliceAngles: SliceAngle[]
): number {
    if (sliceAngles.length === 0 || layout.outerRadius <= 0) {
        return -1
    }
    const dx = cursorX - layout.cx
    const dy = cursorY - layout.cy
    const distance = Math.hypot(dx, dy)
    if (distance > layout.outerRadius || distance < layout.innerRadius) {
        return -1
    }
    // atan2 returns (-π, π]; normalise into [0, 2π) for comparisons.
    const rawAngle = Math.atan2(dy, dx)
    for (const slice of sliceAngles) {
        if (isAngleInRange(rawAngle, slice.startAngle, slice.endAngle)) {
            return slice.sliceIndex
        }
    }
    return -1
}

/** Inclusive on `start`, exclusive on `end`. Handles arbitrary positive/negative
 *  start/end angles by normalising into [0, 2π). */
function isAngleInRange(angle: number, start: number, end: number): boolean {
    const twoPi = Math.PI * 2
    const a = ((angle % twoPi) + twoPi) % twoPi
    const s = ((start % twoPi) + twoPi) % twoPi
    let sweep = end - start
    if (sweep <= 0) {
        return false
    }
    if (sweep >= twoPi) {
        return true
    }
    let delta = a - s
    if (delta < 0) {
        delta += twoPi
    }
    return delta < sweep
}

/** Returns the (x, y) position where a slice's label should be drawn —
 *  on the bisector of the slice at the midpoint between inner and outer radii. */
export function sliceLabelPosition(
    layout: PieLayout,
    angle: SliceAngle,
    hoverOffset: number = 0
): { x: number; y: number; midAngle: number } {
    const midAngle = (angle.startAngle + angle.endAngle) / 2
    const innerR = layout.innerRadius
    const outerR = layout.outerRadius
    const labelR = (innerR + outerR) / 2
    return {
        x: layout.cx + Math.cos(midAngle) * (labelR + hoverOffset),
        y: layout.cy + Math.sin(midAngle) * (labelR + hoverOffset),
        midAngle,
    }
}

/** Returns the offset vector (dx, dy) for a hovered slice — used to "pop out"
 *  the slice along its bisector. Returns (0, 0) for non-hovered slices. */
export function sliceHoverOffset(
    angle: SliceAngle,
    isHovered: boolean,
    hoverOffsetPx: number
): { dx: number; dy: number } {
    if (!isHovered || hoverOffsetPx <= 0) {
        return { dx: 0, dy: 0 }
    }
    const mid = (angle.startAngle + angle.endAngle) / 2
    return { dx: Math.cos(mid) * hoverOffsetPx, dy: Math.sin(mid) * hoverOffsetPx }
}
