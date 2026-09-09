import { group } from 'd3-array'

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
 *
 * `seriesColors` is indexed by series index. The color comes from the series rather than one of its
 * points, so a point-level override — which highlights that one marker — can't repaint the whole
 * line and put it out of step with the legend.
 */
export function computeBestFitSegments(positions: ScatterPointPosition[], seriesColors: string[]): BestFitSegment[] {
    const bySeries = group(positions, (position) => position.seriesIndex)

    const segments: BestFitSegment[] = []
    for (const [seriesIndex, seriesPositions] of bySeries) {
        if (seriesPositions.length < 2) {
            continue
        }
        const { m, b } = linearRegression(seriesPositions.map((position): [number, number] => [position.x, position.y]))
        // Points stacked at a single x leave the gradient a 0/0, which is a vertical line rather than
        // a function of x. Nothing to draw.
        if (!isFinite(m) || !isFinite(b)) {
            continue
        }
        let x0 = Infinity
        let x1 = -Infinity
        for (const position of seriesPositions) {
            x0 = Math.min(x0, position.x)
            x1 = Math.max(x1, position.x)
        }
        // Spans the series' own points instead of the plot, so the line doesn't extrapolate a
        // relationship out over empty space.
        segments.push({ seriesIndex, color: seriesColors[seriesIndex], x0, y0: m * x0 + b, x1, y1: m * x1 + b })
    }
    return segments
}
