import { dimensions, makeSeries } from '../test-helpers'
import { createBarScales } from './scales'

describe('hog-charts bar scales', () => {
    describe('createBarScales — vertical orientation (default)', () => {
        it.each([
            {
                orientation: 'vertical' as const,
                rangeStart: dimensions.plotLeft,
                rangeEnd: dimensions.plotLeft + dimensions.plotWidth,
            },
            {
                orientation: 'horizontal' as const,
                rangeStart: dimensions.plotTop,
                rangeEnd: dimensions.plotTop + dimensions.plotHeight,
            },
        ])('places bands across the categorical axis ($orientation)', ({ orientation, rangeStart, rangeEnd }) => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { band } = createBarScales(series, ['a', 'b', 'c'], dimensions, { axisOrientation: orientation })
            const bandStart = band('a')!
            expect(bandStart).toBeGreaterThanOrEqual(rangeStart)
            expect(bandStart + band.bandwidth()).toBeLessThanOrEqual(rangeEnd + 1)
        })

        it('produces a bandwidth proportional to the number of labels', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2, 3, 4] })]
            const four = createBarScales(series, ['a', 'b', 'c', 'd'], dimensions)
            const two = createBarScales(series, ['a', 'b'], dimensions)
            expect(four.band.bandwidth()).toBeLessThan(two.band.bandwidth())
        })

        it('inverts the value scale so larger values map to smaller y pixels', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            expect(value(100)).toBeLessThan(value(0))
        })

        // Both signs must extend the value domain to include zero so bar baselines align with
        // the plot edge. expectedSign tracks whether the extreme pixel sits above (-1) or below
        // (+1) the zero pixel.
        it.each([
            { sign: 'positive', data: [40, 60, 80], extreme: 80, expectedSign: -1 },
            { sign: 'negative', data: [-40, -60, -80], extreme: -80, expectedSign: 1 },
        ])('extends the value domain to include zero ($sign data)', ({ data, extreme, expectedSign }) => {
            const series = [makeSeries({ key: 's1', data })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            const yAtZero = value(0)
            expect(yAtZero).toBeGreaterThanOrEqual(dimensions.plotTop - 1)
            expect(yAtZero).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
            expect(Math.sign(value(extreme) - yAtZero)).toBe(expectedSign)
        })

        it('returns a group scale only for grouped layout', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2] }), makeSeries({ key: 's2', data: [3, 4] })]
            const stacked = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'stacked' })
            const grouped = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'grouped' })
            expect(stacked.group).toBeUndefined()
            expect(grouped.group).not.toBeUndefined()
            expect(grouped.group!.bandwidth()).toBeLessThan(grouped.band.bandwidth())
        })

        it('uses [0, 1] for the value domain in percent layout', () => {
            const series = [makeSeries({ key: 's1', data: [50, 100, 150] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { barLayout: 'percent' })
            const yAt1 = value(1)
            const yAt0 = value(0)
            expect(yAt1).toBeLessThan(yAt0)
            expect(value.domain()[0]).toBeCloseTo(0)
            expect(value.domain()[1]).toBeCloseTo(1)
        })
    })

    describe('createBarScales — pixel positioning', () => {
        it.each([
            { orientation: 'vertical' as const, expectedSign: -1 },
            { orientation: 'horizontal' as const, expectedSign: 1 },
        ])('places value(50) on the right side of value(0) for $orientation', ({ orientation, expectedSign }) => {
            const series = [makeSeries({ key: 's1', data: [0, 50] })]
            const { value } = createBarScales(series, ['a', 'b'], dimensions, { axisOrientation: orientation })
            expect(Math.sign(value(50) - value(0))).toBe(expectedSign)
        })

        it('makes consecutive band starts equally spaced', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2, 3, 4] })]
            const { band } = createBarScales(series, ['a', 'b', 'c', 'd'], dimensions)
            const a = band('a')!
            const b = band('b')!
            const c = band('c')!
            expect(b - a).toBeCloseTo(c - b, 5)
        })

        it('group bandwidth times series count plus padding does not exceed band bandwidth', () => {
            const seriesArr = [
                makeSeries({ key: 's1', data: [1] }),
                makeSeries({ key: 's2', data: [2] }),
                makeSeries({ key: 's3', data: [3] }),
            ]
            const grouped = createBarScales(seriesArr, ['a'], dimensions, { barLayout: 'grouped' })
            const totalGroupSpan = grouped.group!.bandwidth() * 3
            expect(totalGroupSpan).toBeLessThanOrEqual(grouped.band.bandwidth())
        })
    })

    describe('createBarScales — empty / edge inputs', () => {
        it('returns a [0, 1] value domain when no series are provided', () => {
            const { value } = createBarScales([], ['a', 'b'], dimensions)
            expect(value.domain()).toEqual([0, 1])
        })

        it('uses stackedSeries values for the value domain when provided', () => {
            const rawSeries = [makeSeries({ key: 's1', data: [10] }), makeSeries({ key: 's2', data: [20] })]
            const stackedSeries = [makeSeries({ key: 's1', data: [10] }), makeSeries({ key: 's2', data: [30] })]
            const { value } = createBarScales(rawSeries, ['a'], dimensions, {
                barLayout: 'stacked',
                stackedSeries,
            })
            const yAtStackTop = value(30)
            expect(yAtStackTop).toBeGreaterThanOrEqual(dimensions.plotTop - 1)
            expect(yAtStackTop).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
        })

        it('skips excluded series when building the grouped sub-band', () => {
            const visible = makeSeries({ key: 'visible', data: [10] })
            const excluded = makeSeries({ key: 'excluded', data: [10], visibility: { excluded: true } })
            const { group } = createBarScales([visible, excluded], ['a'], dimensions, { barLayout: 'grouped' })
            expect(group?.('visible')).not.toBeUndefined()
            expect(group?.('excluded')).toBeUndefined()
        })
    })

    describe('createBarScales — log scale', () => {
        it('snaps the domain to enclosing decade boundaries with positive data', () => {
            const series = [makeSeries({ key: 's1', data: [3, 50, 700] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { scaleType: 'log' })
            const [lo, hi] = value.domain()
            expect(lo).toBeLessThanOrEqual(3)
            expect(hi).toBeGreaterThanOrEqual(700)
            expect(value(700)).toBeLessThan(value(3))
        })

        it('falls back to linear when the data has no positive values', () => {
            const series = [makeSeries({ key: 's1', data: [-10, -5, 0] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { scaleType: 'log' })
            const domain = value.domain()
            expect(domain[0]).toBeLessThanOrEqual(-10)
            expect(domain[1]).toBeGreaterThanOrEqual(0)
        })
    })
})
