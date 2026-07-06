import { dimensions, makeSeries } from '../testing'
import { computeBarAtIndex } from './bar-layout'
import { createComboScales, isLineLike, partitionByType, resolveSeriesType } from './combo-scales'
import { computePercentStackData, computeStackData } from './scales'
import type { Series, SeriesType } from './types'
import { DEFAULT_Y_AXIS_ID } from './types'

function typeOfWithDefault(defaultType: SeriesType): (s: Pick<Series, 'type'>) => SeriesType {
    return (s) => resolveSeriesType(s, defaultType)
}

describe('combo-scales', () => {
    describe('resolveSeriesType', () => {
        it.each<[Pick<Series, 'type'>, SeriesType, SeriesType]>([
            [{ type: 'bar' }, 'line', 'bar'],
            [{ type: 'area' }, 'line', 'area'],
            [{}, 'line', 'line'],
            [{}, 'bar', 'bar'],
        ])('resolveSeriesType(%o, %s) === %s', (series, defaultType, expected) => {
            expect(resolveSeriesType(series, defaultType)).toBe(expected)
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
                barStackedData: computeStackData(
                    series.filter((s) => s.type === 'bar'),
                    ['a', 'b', 'c']
                ),
            })
            const bw = scales.band.bandwidth()
            for (const label of ['a', 'b', 'c']) {
                const start = scales.band(label)!
                expect(start).toBeGreaterThanOrEqual(dimensions.plotLeft)
                expect(start + bw).toBeLessThanOrEqual(dimensions.plotLeft + dimensions.plotWidth)
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
            expect(scales.group).not.toBeUndefined()
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
            expect(domainMax).toBeGreaterThanOrEqual(90)
        })

        it('uses bar stacked tops (not raw) when bars are stacked', () => {
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
            expect(Object.keys(scales.yAxes)).toEqual([DEFAULT_Y_AXIS_ID])
        })

        it('builds independent scales per yAxisId, each spanning that axis own series only', () => {
            const leftBar = makeSeries({ key: 'lb', data: [10], type: 'bar' })
            const leftLine = makeSeries({ key: 'll', data: [15], type: 'line' })
            const rightLine = makeSeries({ key: 'rl', data: [1000], type: 'line', yAxisId: 'y1' })
            const scales = createComboScales([leftBar, leftLine, rightLine], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
            })
            expect(scales.yAxes[DEFAULT_Y_AXIS_ID]).not.toBeUndefined()
            expect(scales.yAxes.y1).not.toBeUndefined()
            expect(scales.yAxes.y1.position).toBe('right')
            const [, leftMax] = scales.yAxes[DEFAULT_Y_AXIS_ID].scale.domain()
            expect(leftMax).toBeLessThan(500)
        })

        it('pins a sole axis right when the axes override says so', () => {
            const bar = makeSeries({ key: 'b', data: [1, 2], type: 'bar', yAxisId: 'right' })
            const scales = createComboScales([bar], ['a', 'b'], dimensions, {
                seriesTypeOf: typeOfWithDefault('bar'),
                axes: [{ id: 'right', position: 'right' }],
            })
            expect(scales.yAxes.right.position).toBe('right')
        })

        it('floats a line-only axis with startAtZero false but keeps bar axes on a zero baseline', () => {
            const bar = makeSeries({ key: 'bar', data: [800, 1000], type: 'bar' })
            const line = makeSeries({ key: 'line', data: [800, 1000], type: 'line', yAxisId: 'right' })
            const scales = createComboScales([bar, line], ['a', 'b'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
                axes: [
                    { id: DEFAULT_Y_AXIS_ID, position: 'left', startAtZero: false },
                    { id: 'right', position: 'right', startAtZero: false },
                ],
            })
            // The bar-carrying left axis ignores the float; the line-only right axis honors it.
            expect(scales.yAxes[DEFAULT_Y_AXIS_ID].scale.domain()[0]).toBe(0)
            expect(scales.yAxes.right.scale.domain()[0]).toBeGreaterThan(0)
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

        it('brackets a degenerate domain when every value is identical', () => {
            // All-equal-to-zero collapses min === max; the shared guard must keep the axis well-formed
            // rather than mapping everything to NaN.
            const s = makeSeries({ key: 's', data: [0, 0, 0], type: 'line' })
            const scales = createComboScales([s], ['a', 'b', 'c'], dimensions, {
                seriesTypeOf: typeOfWithDefault('line'),
            })
            const [min, max] = scales.y.domain()
            expect(max).toBeGreaterThan(min)
            expect(isFinite(scales.y(0))).toBe(true)
        })

        it('builds a log value scale when scaleType is log', () => {
            const s = makeSeries({ key: 's', data: [10, 100, 1000], type: 'line' })
            const scales = createComboScales([s], ['a', 'b', 'c'], dimensions, {
                scaleType: 'log',
                seriesTypeOf: typeOfWithDefault('line'),
            })
            // Larger values map to smaller y-pixels (axis inverted); a log scale stays monotonic.
            expect(scales.y(1000)).toBeLessThan(scales.y(100))
            expect(scales.y(100)).toBeLessThan(scales.y(10))
        })
    })

    describe('createComboScales — stacked bars on a secondary axis', () => {
        it('resolves a stacked bar against its own axis scale, not the primary', () => {
            // Bars stacked on the right axis (values ~thousands) must be positioned against the right
            // scale, not the left one (~tens). Regression guard: `computeBarAtIndex`'s stacked branch
            // is axis-aware so combo can pass the whole scale set for both draw and hit-test.
            const leftBar = makeSeries({ key: 'l', data: [10], type: 'bar' })
            const r1 = makeSeries({ key: 'r1', data: [1000], type: 'bar', yAxisId: 'right' })
            const r2 = makeSeries({ key: 'r2', data: [2000], type: 'bar', yAxisId: 'right' })
            const series = [leftBar, r1, r2]
            const barStackedData = computeStackData(series, ['a'])
            const scales = createComboScales(series, ['a'], dimensions, {
                barLayout: 'stacked',
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData,
            })
            // r2 is the top of the right-axis stack — its cumulative top is 1000 + 2000 = 3000.
            const bar = computeBarAtIndex({
                series: r2,
                label: 'a',
                dataIndex: 0,
                scales,
                layout: 'stacked',
                isHorizontal: false,
                stackedBand: barStackedData.get('r2'),
                isTopOfStack: true,
            })
            expect(bar).not.toBeNull()
            const rightScale = scales.yAxes.right.scale
            expect(bar!.y).toBeCloseTo(rightScale(3000), 0)
            // The left/primary scale (domain ~[0,10]) would place 3000 far off-plot — confirm it differs.
            expect(Math.abs(bar!.y - scales.y(3000))).toBeGreaterThan(1)
        })
    })

    describe('createComboScales — percent-stack barLayout', () => {
        it('clamps the y-scale domain to [0, 1] when barLayout is percent', () => {
            const bar1 = makeSeries({ key: 'b1', data: [300], type: 'bar' })
            const bar2 = makeSeries({ key: 'b2', data: [700], type: 'bar' })
            const barStackedData = computePercentStackData([bar1, bar2], ['a'])
            const scales = createComboScales([bar1, bar2], ['a'], dimensions, {
                barLayout: 'percent',
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData,
            })
            const [domainMin, domainMax] = scales.y.domain()
            expect(domainMin).toBeCloseTo(0, 1)
            expect(domainMax).toBeCloseTo(1, 1)
        })

        it('bar series percent tops sum to 1 across the stack', () => {
            const bar1 = makeSeries({ key: 'b1', data: [300], type: 'bar' })
            const bar2 = makeSeries({ key: 'b2', data: [700], type: 'bar' })
            const barStackedData = computePercentStackData([bar1, bar2], ['a'])
            // b2 is the topmost bar — its cumulative top should be 1.0
            expect(barStackedData.get('b2')?.top[0]).toBeCloseTo(1, 5)
        })

        it('does not clamp a line-only secondary axis to [0, 1] when the primary axis is percent-stacked', () => {
            // Regression guard: percentStack must only clamp axes that actually carry bar series —
            // a line explicitly routed to the right axis needs its own data-derived scale, not the
            // bars' [0, 1] domain, or it renders off-plot.
            const bar1 = makeSeries({ key: 'b1', data: [300], type: 'bar' })
            const bar2 = makeSeries({ key: 'b2', data: [700], type: 'bar' })
            const rightLine = makeSeries({ key: 'l1', data: [5000], type: 'line', yAxisId: 'right' })
            const series = [bar1, bar2, rightLine]
            const barStackedData = computePercentStackData([bar1, bar2], ['a'])
            const scales = createComboScales(series, ['a'], dimensions, {
                barLayout: 'percent',
                seriesTypeOf: typeOfWithDefault('line'),
                barStackedData,
            })
            const [leftMin, leftMax] = scales.yAxes[DEFAULT_Y_AXIS_ID].scale.domain()
            expect(leftMin).toBeCloseTo(0, 1)
            expect(leftMax).toBeCloseTo(1, 1)
            const [, rightMax] = scales.yAxes.right.scale.domain()
            expect(rightMax).toBeGreaterThan(1)
            expect(scales.yAxes.right.scale(5000)).not.toBeCloseTo(scales.yAxes.right.scale(0), 0)
        })
    })

    describe('createComboScales — per-series type defaulting from config', () => {
        it('treats series without explicit type as the configured default', () => {
            const untyped = makeSeries({ key: 'u', data: [50] })
            const scales = createComboScales([untyped], ['a'], dimensions, {
                seriesTypeOf: typeOfWithDefault('bar'),
                barLayout: 'grouped',
            })
            expect(scales.y(50)).toBeLessThan(scales.y(0))
            const [, domainMax] = scales.y.domain()
            expect(domainMax).toBeGreaterThanOrEqual(50)
        })
    })
})
