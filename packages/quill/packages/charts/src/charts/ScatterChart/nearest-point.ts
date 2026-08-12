import type { ScatterPointPosition } from './scatter-layout'

// How far past a marker's edge still counts as hovering it, so a small dot doesn't demand
// pixel-perfect aim while empty plot area still reads as empty.
const HOVER_TOLERANCE_PX = 6

/** Global index of the marker nearest the cursor, or -1 when none is in reach. Ranking by distance to
 *  a marker's *edge* lets a large marker the cursor sits inside beat a small one centered nearer.
 *
 *  `positions` must be x-sorted: this binary-searches to the cursor's x, then sweeps outward only
 *  while the x gap alone could still win, bounded by `maxRadius`. */
export function findNearestPointIndex(
    positions: ScatterPointPosition[],
    cursorX: number,
    cursorY: number,
    maxRadius: number
): number {
    let lo = 0
    let hi = positions.length
    while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (positions[mid].x < cursorX) {
            lo = mid + 1
        } else {
            hi = mid
        }
    }

    let best = -1
    let bestScore = HOVER_TOLERANCE_PX
    const scoreAt = (i: number, dx: number): void => {
        const score = Math.hypot(dx, positions[i].y - cursorY) - positions[i].radius
        if (score < bestScore) {
            bestScore = score
            best = positions[i].index
        }
    }
    for (let i = lo; i < positions.length; i++) {
        const dx = positions[i].x - cursorX
        if (dx - maxRadius > bestScore) {
            break
        }
        scoreAt(i, dx)
    }
    for (let i = lo - 1; i >= 0; i--) {
        const dx = cursorX - positions[i].x
        if (dx - maxRadius > bestScore) {
            break
        }
        scoreAt(i, dx)
    }
    return best
}
