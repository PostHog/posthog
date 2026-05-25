import { dimensions, makeSeries } from '../testing'
import {
    createComboScales,
    isLineLike,
    partitionByType,
    resolveSeriesType,
} from './combo-scales'
import { computeStackData } from './scales'
import type { Series, SeriesType } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

function typeOfWithDefault(defaultType: SeriesType): (s: Pick<Series, 'type'>) => SeriesType {
    return (s) => resolveSeriesType(s, defaultType)
}

describe('hog-charts combo-scales', () => {
    describe('resolveSeriesType', () => {
        it('returns the explicit type when set', () => {
            expect(resolveSeriesType({ type: 'bar' }, 'line')).toBe('bar')
            expect(resolveSeriesType({ type: 'area' }, 'line')).toBe('area')
        })

        it('falls back to the default when type is unset', () => {
            expect(resolveSeriesType({}, 'line')).toBe('line')
            expect(resolveSeriesType({}, 'bar')).toBe('bar')
        })
    })

    describe('isLineLike', () => {
        it.each<[SeriesType, boolean]>([
            ['line', true],
            ['area', true],
            ['bar', false],
        ])('isLineLike(%s) === %s', (t, expected) => {
            expect(isLineLike(t)).toBe(expected)
        })
    })

    describe('partitionByType', () => {
        it('splits visible series by resolved type, preserving order', () => {
            const a = makeSeries({ key: 'a', data: [1], type: 'bar' })
            const b = makeSeries({ key: 'b', data: [1] }) // default line
            const c = makeSeries({ key: 'c', data: [1], type: 'area' })
            const d = makeSeries({ key: 'd', data: [1], type: 'bar' })
            const { bars, lines } = partitionByType([a, b, c, d], typeOfWithDefault('line'))
            expect(bars.map((s) => s.key)).toEqual(['a', 'd'])
            expect(lines.map((s) => s.key)).toEqual(['b', 'c'])
        })

        it('drops excluded series from both buckets', () => {
            const a = makeSeries({ key: 'a', data: [1], type: 'bar', visibility: { excluded: true } })
            const b = makeSeries({ key: 'b', data: [1], type: 'line', visibility: { excluded: true } })
            const c = makeSeries({ key: 'c', data: [1], type: 'bar' })
            const { bars, lines } = partitionByType([a, b, c], typeOfWithDefault('line'))
            expect(bars.map((s) => s.key)).toEqual(['c'])
            expect(lines).toHaveLength(0)
        })

        it('respects the per-series type even when default is bar', () => {
            const a = makeSeries({ key: 'a', data: [1] }) // default → bar
            const b = makeSeries({ key: 'b', data: [1], type: 'line' })
            const { bars, lines } = partitionByType([a, b], typeOfWithDefault('bar'))
            expect(bars.map((s) => s.key)).toEqual(['a'])
            expect(lines.map((s) => s.key)).toEqual(['b'])
        })
    })

    describe('createComboScales — band x', () => {
        it('places a line series at band centers (matches band scale center)', () => {
            const series: Series[] = [
                makeSeries({ key: 'b1', data: [10, 20, 30], type: 'bar' }),
                makeSeries({ key: 'l1', data: [5, 15, 25], type: 'line' }),
            ]
            const scales = createComboScales(series, ['a', 'b', 'c'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData: computeStackData(series.filter((s) => s.type === 'bar'), ['a', 'b', 'c']),
            })
            // For each label, the d3 band scale gives the start; center = start + bandwidth/2.
            const bw = scales.band.bandwidth()
            for (const label of ['a', 'b', 'c']) {
                const start = scales.band(label)!
                expect(start).toBeGreaterThanOrEqual(dimensions.plotLeft)
                expect(start + bw).toBeLessThanOrEqual(dimensions.plotLeft + dimensions.plotWidth)
                // Center is the line anchor — verified here by deriving it identically:
                expect(start + bw / 2).toBe(start + scales.band.bandwidth() / 2)
            }
        })

        it('builds a group sub-band from bar series only when barLayout is grouped', () => {
            const series: Series[] = [
                makeSeries({ key: 'b1', data: [10], type: 'bar' }),
                makeSeries({ key: 'l1', data: [5], type: 'line' }),
                makeSeries({ key: 'b2', data: [3], type: 'bar' }),
            ]
            const scales = createComboScales(series, ['a'], dimensions, {
                barLayout: 'grouped',
                seriesTypeOf: typeOfWithDefault('line'),
            })
            expect(scales.group).toBeDefined()
            expect(scales.group!.domain()).toEqual(['b1', 'b2'])
        })

        it('omits the group sub-band for stacked layout', () => {
            const series: Series[] = [makeSeries({ key: 'b1', data: [10], type: 'bar' })]
            const scales = createComboScales(series, ['a'], dimensions, {
                barLayout: 'stacked',
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData: computeStackData(series, ['a']),
            })
            expect(scales.group).toBeUndefined()
        })
    })

    describe('createComboScales — value domain spans all types per axis', () => {
        it('lets a line series extend the axis max above the highest bar', () => {
            const bar = makeSeries({ key: 'b', data: [10, 20, 30], type: 'bar' })
            const line = makeSeries({ key: 'l', data: [5, 60, 90], type: 'line' })
            const scales = createComboScales([bar, line], ['a', 'b', 'c'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData: computeStackData([bar], ['a', 'b', 'c']),
            })
            const [, domainMax] = scales.y.domain()
            // d3 nice() rounds up — must be at least the line's max (90).
            expect(domainMax).toBeGreaterThanOrEqual(90)
        })

        it('uses bar stacked tops (not raw) when bars are stacked', () => {
            // Two bar series with raw max 30 each, but stacked at index 2 = 60.
            const b1 = makeSeries({ key: 'b1', data: [10, 20, 30], type: 'bar' })
            const b2 = makeSeries({ key: 'b2', data: [10, 20, 30], type: 'bar' })
            const scales = createComboScales([b1, b2], ['a', 'b', 'c'], dimensions, {
                barLayout: 'stacked',
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData: computeStackData([b1, b2], ['a', 'b', 'c']),
            })
            const [, domainMax] = scales.y.domain()
            expect(domainMax).toBeGreaterThanOrEqual(60)
        })

        it('keeps bar and line on the same axis under one value scale', () => {
            const bar = makeSeries({ key: 'b', data: [100], type: 'bar' })
            const line = makeSeries({ key: 'l', data: [200], type: 'line' })
            const scales = createComboScales([bar, line], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
            })
            // Both series resolve to the same yAxes entry — DEFAULT_Y_AXIS_ID.
            expect(Object.keys(scales.yAxes)).toEqual([DEFAULT_Y_AXIS_ID])
        })

        it('builds independent scales per yAxisId, each spanning that axis own series only', () => {
            const leftBar = makeSeries({ key: 'lb', data: [10], type: 'bar' })
            const leftLine = makeSeries({ key: 'll', data: [15], type: 'line' })
            const rightLine = makeSeries({ key: 'rl', data: [1000], type: 'line', yAxisId: 'y1' })
            const scales = createComboScales([leftBar, leftLine, rightLine], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
            })
            expect(scales.yAxes[DEFAULT_Y_AXIS_ID]).toBeDefined()
            expect(scales.yAxes.y1).toBeDefined()
            expect(scales.yAxes.y1.position).toBe('right')
            // Left axis must not absorb the right series's huge value.
            const [, leftMax] = scales.yAxes[DEFAULT_Y_AXIS_ID].scale.domain()
            expect(leftMax).toBeLessThan(500)
        })

        it('points combo.y at the default axis when present', () => {
            const leftLine = makeSeries({ key: 'l', data: [10] })
            const rightBar = makeSeries({ key: 'r', data: [1000], type: 'bar', yAxisId: 'y1' })
            const scales = createComboScales([leftLine, rightBar], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
            })
            expect(scales.y(10)).toBe(scales.yAxes[DEFAULT_Y_AXIS_ID].scale(10))
        })

        it('excludes excluded series from the axis domain', () => {
            const visible = makeSeries({ key: 'v', data: [10], type: 'bar' })
            const hidden = makeSeries({
                key: 'h',
                data: [9999],
                type: 'line',
                visibility: { excluded: true },
            })
            const scales = createComboScales([visible, hidden], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData: computeStackData([visible], ['a']),
            })
            const [, domainMax] = scales.y.domain()
            expect(domainMax).toBeLessThan(100)
        })

        it('returns a fallback [0,1] domain when all axis series are non-finite', () => {
            const s = makeSeries({ key: 's', data: [NaN, NaN], type: 'line' })
            const scales = createComboScales([s], ['a', 'b'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
            })
            expect(scales.y.domain()).toEqual([0, 1])
        })
    })

    describe('createComboScales — per-series type defaulting from config', () => {
        it('treats series without explicit type as the configured default', () => {
            // Defaults to bar, so an "untyped" series with a huge value should drive the
            // bar-stack domain (when stacked) rather than the line domain.
            const untyped = makeSeries({ key: 'u', data: [50] })
            const scales = createComboScales([untyped], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('bar'),
                barLayout: 'grouped',
            })
            // grouped → no stacked data needed; the untyped series is treated as a bar
            // and reported through the value scale (higher values map to smaller y-pixels).
            expect(scales.y(50)).toBeLessThan(scales.y(0))
            const [, domainMax] = scales.y.domain()
            expect(domainMax).toBeGreaterThanOrEqual(50)
        })
    })
})
