import { findNearestPointIndex } from './nearest-point'
import type { ScatterPointPosition } from './scatter-layout'

function position(index: number, x: number, y: number, radius = 4): ScatterPointPosition {
    return { index, x, y, radius, color: '#000', shape: 'circle' }
}

describe('findNearestPointIndex', () => {
    // Two points share an x pixel: the case an x-only bisector (what line and bar charts use) can't
    // resolve, and the reason the scatter chart hit-tests in 2D.
    const stacked = [position(0, 100, 20), position(1, 100, 200)]

    it.each([
        ['the upper point', 22, 0],
        ['the lower point', 198, 1],
    ])('picks %s when two points share an x position', (_, cursorY, expected) => {
        expect(findNearestPointIndex(stacked, 100, cursorY, 4)).toBe(expected)
    })

    it('reports no hit when the cursor is in empty plot area', () => {
        expect(findNearestPointIndex(stacked, 400, 110, 4)).toBe(-1)
    })

    it('hits a marker from just outside its edge but not from beyond the slop', () => {
        const points = [position(7, 100, 100, 4)]
        expect(findNearestPointIndex(points, 109, 100, 4)).toBe(7)
        expect(findNearestPointIndex(points, 111, 100, 4)).toBe(-1)
    })

    it('prefers a large marker the cursor sits inside over a small one whose center is nearer', () => {
        // The small marker's center is 5px away, the large one's is 8px, but the cursor is inside the
        // large marker, so that is what the user is pointing at.
        const points = [position(0, 92, 100, 10), position(1, 105, 100, 2)]
        expect(findNearestPointIndex(points, 100, 100, 10)).toBe(0)
    })

    it('returns no hit for an empty plot', () => {
        expect(findNearestPointIndex([], 100, 100, 0)).toBe(-1)
    })
})
