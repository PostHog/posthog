import { findNearestIndex } from '../../../core/interaction'
import { createComboScales } from '../../../core/combo-scales'
import { computeStackData } from '../../../core/scales'
import { dimensions, makeSeries } from '../../../testing'
import type { Series, SeriesType } from '../../../core/types'
import { barKeysAtCursor } from './combo-hit-test'

const seriesTypeOf =
    (defaultType: SeriesType): ((s: Pick<Series, 'type'>) => SeriesType) =>
    (s) =>
        s.type ?? defaultType

describe('combo hit-test', () => {
    describe('nearest-column selection (bandCenter)', () => {
        it('returns the index whose band center is closest to the cursor x', () => {
            const labels = ['Mon', 'Tue', 'Wed', 'Thu']
            const scales = createComboScales([], labels, dimensions, { seriesTypeOf: seriesTypeOf('line') })
            const bandCenter = (label: string): number | undefined => {
                const start = scales.band(label)
                return start == null ? undefined : start + scales.band.bandwidth() / 2
            }
            for (const target of [0, 1, 2, 3]) {
                const cursorX = bandCenter(labels[target])!
                expect(findNearestIndex(cursorX, labels, bandCenter)).toBe(target)
            }
        })

        it('rounds to the nearer index between two band centers', () => {
            const labels = ['a', 'b', 'c']
            const scales = createComboScales([], labels, dimensions, { seriesTypeOf: seriesTypeOf('line') })
            const bandCenter = (label: string): number | undefined => {
                const start = scales.band(label)
                return start == null ? undefined : start + scales.band.bandwidth() / 2
            }
            const ca = bandCenter('a')!
            const cb = bandCenter('b')!
            // Slightly past midpoint toward b → picks b.
            expect(findNearestIndex(ca + (cb - ca) * 0.55, labels, bandCenter)).toBe(1)
            // Slightly before midpoint → picks a.
            expect(findNearestIndex(ca + (cb - ca) * 0.45, labels, bandCenter)).toBe(0)
        })
    })

    describe('barKeysAtCursor (band-axis hit)', () => {
        it('returns only bar series whose band-axis extent contains the cursor x', () => {
            const labels = ['Mon', 'Tue']
            const bar = makeSeries({ key: 'b', data: [10, 20], type: 'bar' })
            const line = makeSeries({ key: 'l', data: [5, 15], type: 'line' })
            const scales = createComboScales([bar, line], labels, dimensions, {
                barLayout: 'stacked',
                seriesTypeOf: seriesTypeOf('line'),
                barStackedData: computeStackData([bar], labels),
            })
            const bandStart = scales.band('Tue')!
            const cursor = { x: bandStart + scales.band.bandwidth() / 2, y: dimensions.plotTop + 50 }
            const hits = barKeysAtCursor({
                series: [bar, line],
                label: 'Tue',
                dataIndex: 1,
                cursor,
                scales,
                layout: 'stacked',
                barStackedData: computeStackData([bar], labels),
                topStackedKeyByAxis: new Map([['left', 'b']]),
                defaultSeriesType: 'line',
            })
            // The bar is hit; the line is not bar-typed so it's never in the set.
            expect(hits).toEqual(new Set(['b']))
        })

        it('returns an empty set when the cursor is in the gap between bands', () => {
            const labels = ['Mon', 'Tue', 'Wed']
            const bar = makeSeries({ key: 'b', data: [10, 20, 30], type: 'bar' })
            const scales = createComboScales([bar], labels, dimensions, {
                barLayout: 'stacked',
                seriesTypeOf: seriesTypeOf('line'),
                barStackedData: computeStackData([bar], labels),
            })
            // Just past the right edge of band "Mon" but before "Tue" — in the padding gap.
            const monEnd = scales.band('Mon')! + scales.band.bandwidth()
            const tueStart = scales.band('Tue')!
            const cursor = { x: (monEnd + tueStart) / 2, y: dimensions.plotTop + 50 }
            const hits = barKeysAtCursor({
                series: [bar],
                label: 'Mon',
                dataIndex: 0,
                cursor,
                scales,
                layout: 'stacked',
                barStackedData: computeStackData([bar], labels),
                topStackedKeyByAxis: new Map([['left', 'b']]),
                defaultSeriesType: 'line',
            })
            expect(hits.size).toBe(0)
        })

        it('grouped layout narrows to the bar whose sub-band slot the cursor occupies', () => {
            const labels = ['a']
            const b1 = makeSeries({ key: 'b1', data: [10], type: 'bar' })
            const b2 = makeSeries({ key: 'b2', data: [20], type: 'bar' })
            const scales = createComboScales([b1, b2], labels, dimensions, {
                barLayout: 'grouped',
                seriesTypeOf: seriesTypeOf('line'),
            })
            const bandStart = scales.band('a')!
            const b2Offset = scales.group!('b2')!
            // Cursor inside b2's sub-band slot.
            const cursor = {
                x: bandStart + b2Offset + scales.group!.bandwidth() / 2,
                y: dimensions.plotTop + 50,
            }
            const hits = barKeysAtCursor({
                series: [b1, b2],
                label: 'a',
                dataIndex: 0,
                cursor,
                scales,
                layout: 'grouped',
                topStackedKeyByAxis: new Map(),
                defaultSeriesType: 'line',
            })
            expect(hits).toEqual(new Set(['b2']))
        })

        it('uses the per-axis value scale (dual-axis) when resolving the bar rect', () => {
            // Right-axis bar with a huge value — without per-axis resolution the bar would
            // map against the left-axis (max 10), pushing the bar way above the plot and the
            // hit test would still pass because it's band-axis only. The point of this test
            // is that the function doesn't *throw* and still returns the correct hit using
            // the right-axis scale.
            const labels = ['a']
            const leftBar = makeSeries({ key: 'l', data: [5], type: 'bar' })
            const rightBar = makeSeries({ key: 'r', data: [5000], type: 'bar', yAxisId: 'y1' })
            const scales = createComboScales([leftBar, rightBar], labels, dimensions, {
                barLayout: 'grouped',
                seriesTypeOf: seriesTypeOf('line'),
            })
            const bandStart = scales.band('a')!
            const rOffset = scales.group!('r')!
            const cursor = {
                x: bandStart + rOffset + scales.group!.bandwidth() / 2,
                y: dimensions.plotTop + 50,
            }
            const hits = barKeysAtCursor({
                series: [leftBar, rightBar],
                label: 'a',
                dataIndex: 0,
                cursor,
                scales,
                layout: 'grouped',
                topStackedKeyByAxis: new Map(),
                defaultSeriesType: 'line',
            })
            expect(hits).toEqual(new Set(['r']))
        })
    })
})
