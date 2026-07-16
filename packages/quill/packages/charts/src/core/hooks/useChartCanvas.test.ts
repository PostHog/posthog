import { buildDimensions } from './useChartCanvas'

const MARGINS = { top: 16, right: 16, bottom: 32, left: 48 }

function rect(width: number, height: number): DOMRect {
    return { width, height, x: 0, y: 0, top: 0, left: 0, right: width, bottom: height, toJSON: () => ({}) } as DOMRect
}

describe('buildDimensions', () => {
    it('subtracts the margins from a measured rect', () => {
        const d = buildDimensions(rect(600, 400), MARGINS)
        expect(d.plotWidth).toBe(600 - 48 - 16)
        expect(d.plotHeight).toBe(400 - 16 - 32)
    })

    // `Math.max(0, NaN)` is NaN, so a non-finite rect/margin used to poison the plot size — a NaN
    // pixel range maps every point and axis tick to NaN, blanking the chart while x-only tooltips
    // still fire. Every dimension must stay finite and non-negative.
    it.each([
        { name: 'a NaN height', r: rect(600, NaN) },
        { name: 'an infinite height', r: rect(600, Infinity) },
        { name: 'a NaN width', r: rect(NaN, 400) },
        { name: 'a zero-size rect', r: rect(0, 0) },
    ])('floors the plot size to a finite, non-negative value for $name', ({ r }) => {
        const d = buildDimensions(r, MARGINS)
        expect(isFinite(d.plotWidth)).toBe(true)
        expect(isFinite(d.plotHeight)).toBe(true)
        expect(d.plotWidth).toBeGreaterThanOrEqual(0)
        expect(d.plotHeight).toBeGreaterThanOrEqual(0)
    })
})
