import { makeSeries } from '../testing'
import { computeBandSlot, cursorInsideBandSlot, seriesKeysAtCursor } from './band-slot'
import { createBarScales } from './scales'
import type { ChartDimensions } from './types'

const DIMS: ChartDimensions = {
    width: 400,
    height: 200,
    plotLeft: 0,
    plotTop: 0,
    plotWidth: 400,
    plotHeight: 200,
}

const LABELS = ['Mon', 'Tue', 'Wed']

function scalesFor(seriesKeys: string[], barLayout: 'grouped' | 'stacked'): ReturnType<typeof createBarScales> {
    const series = seriesKeys.map((key) => makeSeries({ key, data: [1, 2, 3] }))
    return createBarScales(series, LABELS, DIMS, { barLayout })
}

describe('band-slot', () => {
    describe('computeBandSlot', () => {
        it('returns the whole band for a single series', () => {
            const scales = scalesFor(['a'], 'stacked')
            const slot = computeBandSlot('a', 'Tue', scales, false)

            expect(slot).toEqual({ x: scales.band('Tue'), width: scales.band.bandwidth() })
        })

        it('returns the series sub-band inside the band when grouped', () => {
            const scales = scalesFor(['a', 'b'], 'grouped')
            const first = computeBandSlot('a', 'Tue', scales, true)
            const second = computeBandSlot('b', 'Tue', scales, true)

            expect(first).not.toBeNull()
            expect(second).not.toBeNull()
            expect(first!.width).toBeLessThan(scales.band.bandwidth())
            expect(second!.x).toBeGreaterThan(first!.x)
            expect(first!.x).toBeGreaterThanOrEqual(scales.band('Tue')!)
        })

        it('returns null for a label outside the band domain', () => {
            const scales = scalesFor(['a'], 'stacked')

            expect(computeBandSlot('a', 'Sun', scales, false)).toBeNull()
        })

        it('returns null for a series missing from the group scale', () => {
            const scales = scalesFor(['a', 'b'], 'grouped')

            expect(computeBandSlot('missing', 'Tue', scales, true)).toBeNull()
        })
    })

    describe('cursorInsideBandSlot', () => {
        const slot = { x: 10, width: 40 }

        it.each([
            ['cursor left of slot', { x: 5, y: 30 }, false, false],
            ['cursor on left edge', { x: 10, y: 0 }, false, true],
            ['cursor inside slot', { x: 30, y: 0 }, false, true],
            ['cursor on right edge', { x: 50, y: 0 }, false, true],
            ['cursor right of slot', { x: 60, y: 30 }, false, false],
            ['horizontal: cursor inside the band on y, outside on x', { x: 90, y: 30 }, true, true],
            ['horizontal: cursor outside the band on y, inside on x', { x: 30, y: 90 }, true, false],
        ])('%s', (_name, cursor, horizontal, expected) => {
            expect(cursorInsideBandSlot(slot, cursor, horizontal)).toBe(expected)
        })
    })

    describe('seriesKeysAtCursor', () => {
        const TWO_LABELS = ['Mon', 'Tue']
        const SHAPE = { present: true }

        function subBandCenter(scales: ReturnType<typeof createBarScales>, label: string, key: string): number {
            return scales.band(label)! + scales.group!(key)! + scales.group!.bandwidth() / 2
        }

        it('finds the series under the cursor in a grouped layout', () => {
            const series = [
                { key: 'a', data: [SHAPE, SHAPE] },
                { key: 'b', data: [SHAPE, SHAPE] },
            ]
            const scales = createBarScales(
                series.map((s) => makeSeries({ key: s.key, data: [1, 2] })),
                TWO_LABELS,
                DIMS,
                { barLayout: 'grouped' }
            )
            const hitsAt = (x: number): string[] =>
                Array.from(
                    seriesKeysAtCursor({
                        series,
                        label: 'Mon',
                        dataIndex: 0,
                        cursor: { x, y: 100 },
                        scales,
                        grouped: true,
                    })
                )

            expect(hitsAt(subBandCenter(scales, 'Mon', 'a'))).toEqual(['a'])
            expect(hitsAt(subBandCenter(scales, 'Mon', 'b'))).toEqual(['b'])
        })

        it('returns empty when the cursor is in the gap before a band', () => {
            const series = [{ key: 'a', data: [SHAPE, SHAPE] }]
            const scales = createBarScales([makeSeries({ key: 'a', data: [1, 2] })], TWO_LABELS, DIMS, {
                barLayout: 'stacked',
            })

            const hits = seriesKeysAtCursor({
                series,
                label: 'Mon',
                dataIndex: 0,
                cursor: { x: scales.band('Mon')! - 5, y: 100 },
                scales,
                grouped: false,
            })

            expect(hits.size).toBe(0)
        })

        it('skips excluded series even at their own sub-band', () => {
            const series = [
                { key: 'a', data: [SHAPE, SHAPE] },
                { key: 'b', data: [SHAPE, SHAPE], visibility: { excluded: true } },
            ]
            const scales = createBarScales(
                series.map((s) => makeSeries({ key: s.key, data: [1, 2], visibility: s.visibility })),
                TWO_LABELS,
                DIMS,
                { barLayout: 'grouped' }
            )

            const hits = seriesKeysAtCursor({
                series,
                label: 'Mon',
                dataIndex: 0,
                cursor: { x: scales.band('Mon')! + scales.band.bandwidth() * 0.9, y: 100 },
                scales,
                grouped: true,
            })

            expect(hits.has('b')).toBe(false)
        })

        it('skips an index where the series has no shape', () => {
            const series = [{ key: 'a', data: [SHAPE, null] }]
            const scales = createBarScales([makeSeries({ key: 'a', data: [1, 2] })], TWO_LABELS, DIMS, {
                barLayout: 'stacked',
            })

            const hits = seriesKeysAtCursor({
                series,
                label: 'Tue',
                dataIndex: 1,
                cursor: { x: scales.band('Tue')! + scales.band.bandwidth() / 2, y: 100 },
                scales,
                grouped: false,
            })

            expect(hits.size).toBe(0)
        })
    })
})
