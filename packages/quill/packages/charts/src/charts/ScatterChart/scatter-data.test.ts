import { flattenScatterPoints, scatterValueRange } from './scatter-data'
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

describe('scatter-data', () => {
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
            expect(flattenScatterPoints(series, options)).toMatchObject([{ x: 5, y: 5 }])
        })

        it('keeps a non-positive coordinate when that axis is linear', () => {
            const series: ScatterSeries[] = [{ key: 'a', label: 'A', points: [{ x: 0, y: -5 }] }]
            expect(flattenScatterPoints(series)).toMatchObject([{ x: 0, y: -5 }])
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
})
