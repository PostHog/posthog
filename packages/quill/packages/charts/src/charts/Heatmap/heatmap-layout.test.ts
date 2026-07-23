import type { ChartDimensions } from '../../core/types'
import { cellRect, computeHeatmapLayout, maxCellValue, normalizeCount, rowAtY } from './heatmap-layout'

const DIMENSIONS: ChartDimensions = {
    width: 500,
    height: 300,
    plotLeft: 50,
    plotTop: 20,
    plotWidth: 400,
    plotHeight: 200,
}

describe('heatmap-layout', () => {
    // Row 0 must be the BOTTOM row (ascending value axis). Flipping this silently inverts
    // every tooltip, hover highlight, and brush mapping downstream.
    it('lays rows out bottom-to-top and maps pixels back to the same rows', () => {
        const layout = computeHeatmapLayout(DIMENSIONS, 10, 4) // rowHeight 50
        expect(cellRect(layout, 0, 0)).toEqual({ x: 50, y: 170, width: 40, height: 50 }) // bottom row
        expect(cellRect(layout, 9, 3)).toEqual({ x: 410, y: 20, width: 40, height: 50 }) // top-right

        expect(rowAtY(layout, 219)).toBe(0) // just above the plot bottom
        expect(rowAtY(layout, 21)).toBe(3) // just below the plot top
        expect(rowAtY(layout, 250)).toBe(-1) // below the plot
        expect(rowAtY(layout, 10)).toBe(-1) // above the plot
    })

    it.each([
        ['zero count maps to 0', 0, 100, 'log', 0],
        ['zero max maps to 0 (all-empty grid)', 5, 0, 'log', 0],
        ['max count maps to 1', 100, 100, 'log', 1],
        ['linear is proportional', 50, 100, 'linear', 0.5],
    ] as const)('normalizeCount: %s', (_name, count, max, scale, expected) => {
        expect(normalizeCount(count, max, scale)).toBeCloseTo(expected)
    })

    it('log normalization lifts small counts above linear so the long tail stays visible', () => {
        expect(normalizeCount(2, 1000, 'log')).toBeGreaterThan(normalizeCount(2, 1000, 'linear'))
    })

    it('maxCellValue ignores non-finite values', () => {
        expect(maxCellValue([[1, Number.NaN], [Number.POSITIVE_INFINITY, 7]])).toBe(7)
    })
})
