import { flattenScatterPoints, scatterValueRange } from './scatter-data'
import type { ScatterSeries } from './types'

describe('scatter-data', () => {
    it('interleaves every series into one x-sorted list that remembers where each point came from', () => {
        const series: ScatterSeries[] = [
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
        expect(flattenScatterPoints(series).map((p) => [p.x, p.seriesKey, p.pointIndex])).toEqual([
            [10, 'a', 1],
            [20, 'b', 0],
            [30, 'a', 0],
        ])
    })

    it.each<[string, { x: number; y: number }, Parameters<typeof flattenScatterPoints>[1], { x: number }[]]>([
        ['a non-finite x', { x: NaN, y: 1 }, undefined, [{ x: 5 }]],
        ['a non-finite y', { x: 1, y: Infinity }, undefined, [{ x: 5 }]],
        ['a zero on a log x axis', { x: 0, y: 1 }, { xLogScale: true }, [{ x: 5 }]],
        ['a negative on a log y axis', { x: 1, y: -5 }, { yLogScale: true }, [{ x: 5 }]],
        // A linear axis has room for both, so an over-eager filter fails this row.
        ['a non-positive coordinate on a linear axis', { x: 0, y: -5 }, undefined, [{ x: 0 }, { x: 5 }]],
    ])('keeps only what it can plot, given %s', (_, point, options, expected) => {
        const series: ScatterSeries[] = [{ key: 'a', label: 'A', points: [point, { x: 5, y: 5 }] }]
        expect(flattenScatterPoints(series, options)).toMatchObject(expected)
    })

    it('ranges each axis independently, and reports the smallest positive value for log domains', () => {
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
