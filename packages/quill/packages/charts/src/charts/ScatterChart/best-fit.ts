import { linearRegression } from '../../utils/statistics'
import type { ScatterPointPosition } from './scatter-layout'

/** A fit line's endpoints, already in pixels. */
export interface BestFitSegment {
    seriesIndex: number
    color: string
    x0: number
    y0: number
    x1: number
    y1: number
}

/**
 * Least squares fit per series, computed over the points' pixel positions rather than their values.
 * Each axis scale is affine in its own space, so fitting the pixels minimizes the same residuals as
 * fitting the values on a linear axis, and the log values on a log one — the power-law fit a log
 * axis implies. Either way the result is straight on screen, which is what a fit line has to be.
 *
 * Working off `positions` also means the fit sees exactly the drawn points: those a log axis or a
 * pinned domain dropped, and those a legend toggle hid, are already gone.
 */
export function computeBestFitSegments(positions: ScatterPointPosition[]): BestFitSegment[] {
    const bySeries = new Map<number, ScatterPointPosition[]>()
    for (const position of positions) {
        const group = bySeries.get(position.seriesIndex)
        if (group) {
            group.push(position)
        } else {
            bySeries.set(position.seriesIndex, [position])
        }
    }

    const segments: BestFitSegment[] = []
    for (const [seriesIndex, group] of bySeries) {
        if (group.length < 2) {
            continue
        }
        const { m, b } = linearRegression(group.map((position): [number, number] => [position.x, position.y]))
        // Points stacked at a single x leave the gradient a 0/0, which is a vertical line rather than
        // a function of x. Nothing to draw.
        if (!isFinite(m) || !isFinite(b)) {
            continue
        }
        let x0 = Infinity
        let x1 = -Infinity
        for (const position of group) {
            x0 = Math.min(x0, position.x)
            x1 = Math.max(x1, position.x)
        }
        // Spans the series' own points instead of the plot, so the line doesn't extrapolate a
        // relationship out over empty space.
        segments.push({ seriesIndex, color: group[0].color, x0, y0: m * x0 + b, x1, y1: m * x1 + b })
    }
    return segments
}
