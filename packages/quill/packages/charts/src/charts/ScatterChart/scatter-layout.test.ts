import { findNearestPointIndex, flattenScatterPoints, scatterValueRange } from './scatter-layout'
import type { ScatterPointPosition } from './scatter-layout'
import type { ScatterSeries } from './types'

const SERIES: ScatterSeries[] = [
    {
        key: 'a',
        label: 'A',
        points: [
            { x: 30, y: 1 },
            { x: 10, y: 2 },
        ],
    },
    { key: 'b', label: 'B', points: [{ x: 20, y: 3 }] },
]

function position(index: number, x: number, y: number, radius = 4): ScatterPointPosition {
    return { index, x, y, radius, color: '#000', shape: 'circle' }
}

describe('scatter-layout', () => {
    describe('flattenScatterPoints', () => {
        it('interleaves every series into one x-sorted list that remembers where each point came from', () => {
            expect(flattenScatterPoints(SERIES).map((p) => [p.x, p.seriesKey, p.pointIndex])).toEqual([
                [10, 'a', 1],
                [20, 'b', 0],
                [30, 'a', 0],
            ])
        })

        it.each<[string, { x: number; y: number }, Parameters<typeof flattenScatterPoints>[1]]>([
            ['a non-finite x', { x: NaN, y: 1 }, undefined],
            ['a non-finite y', { x: 1, y: Infinity }, undefined],
            ['a zero on a log x axis', { x: 0, y: 1 }, { xLogScale: true }],
            ['a negative on a log y axis', { x: 1, y: -5 }, { yLogScale: true }],
        ])('drops a point with %s', (_, point, options) => {
            const series: ScatterSeries[] = [{ key: 'a', label: 'A', points: [point, { x: 5, y: 5 }] }]
            expect(flattenScatterPoints(series, options)).toHaveLength(1)
        })

        it('keeps a non-positive coordinate when that axis is linear', () => {
            const series: ScatterSeries[] = [{ key: 'a', label: 'A', points: [{ x: 0, y: -5 }] }]
            expect(flattenScatterPoints(series)).toHaveLength(1)
        })
    })

    describe('scatterValueRange', () => {
        it('spans each axis independently and reports the smallest positive value for log domains', () => {
            const points = flattenScatterPoints([
                {
                    key: 'a',
                    label: 'A',
                    points: [
                        { x: -4, y: 2 },
                        { x: 8, y: 60 },
                    ],
                },
            ])
            expect(scatterValueRange(points, 'x')).toMatchObject({ min: -4, max: 8, minPositive: 8, count: 2 })
            expect(scatterValueRange(points, 'y')).toMatchObject({ min: 2, max: 60, minPositive: 2, count: 2 })
        })
    })

    describe('findNearestPointIndex', () => {
        // Two points share an x pixel — the case an x-only bisector (what line and bar charts use)
        // can't resolve, and the reason the scatter chart hit-tests in 2D.
        const stacked = [position(0, 100, 20), position(1, 100, 200)]

        it.each([
            ['the upper point', 22, 0],
            ['the lower point', 198, 1],
        ])('picks %s when two points share an x position', (_, cursorY, expected) => {
            expect(findNearestPointIndex(stacked, 100, cursorY, 6, 4)).toBe(expected)
        })

        it('reports no hit when the cursor is in empty plot area', () => {
            expect(findNearestPointIndex(stacked, 400, 110, 6, 4)).toBe(-1)
        })

        it('hits a marker from just outside its edge but not from beyond the slop', () => {
            const points = [position(7, 100, 100, 4)]
            expect(findNearestPointIndex(points, 109, 100, 6, 4)).toBe(7)
            expect(findNearestPointIndex(points, 111, 100, 6, 4)).toBe(-1)
        })

        it('prefers a large marker the cursor sits inside over a small one whose center is nearer', () => {
            // The small marker's center is 5px away, the large one's is 8px — but the cursor is
            // inside the large marker, so that is what the user is pointing at.
            const points = [position(0, 92, 100, 10), position(1, 105, 100, 2)]
            expect(findNearestPointIndex(points, 100, 100, 6, 10)).toBe(0)
        })

        it('returns no hit for an empty plot', () => {
            expect(findNearestPointIndex([], 100, 100, 6, 0)).toBe(-1)
        })
    })
})
