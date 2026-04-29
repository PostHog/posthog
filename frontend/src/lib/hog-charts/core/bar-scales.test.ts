import { createBarScales } from '../core/scales'
import { dimensions, makeSeries } from '../test-helpers'

describe('hog-charts bar scales', () => {
    describe('createBarScales — vertical orientation (default)', () => {
        it('builds a band scale across the plot width', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { band } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            const bandStart = band('a')!
            expect(bandStart).toBeGreaterThanOrEqual(dimensions.plotLeft)
            expect(bandStart + band.bandwidth()).toBeLessThanOrEqual(dimensions.plotLeft + dimensions.plotWidth + 1)
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

        it('extends the value domain to include zero when all data is positive', () => {
            const series = [makeSeries({ key: 's1', data: [40, 60, 80] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            // 0 should be at the bottom of the plot area
            const yAtZero = value(0)
            expect(yAtZero).toBeGreaterThan(dimensions.plotTop)
        })

        it('extends the value domain to include zero when all data is negative', () => {
            const series = [makeSeries({ key: 's1', data: [-40, -60, -80] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions)
            const yAtZero = value(0)
            // zero should be at the top of the plot area, with negatives below
            expect(value(-80)).toBeGreaterThan(yAtZero)
        })

        it('returns a group scale only for grouped layout', () => {
            const series = [makeSeries({ key: 's1', data: [1, 2] }), makeSeries({ key: 's2', data: [3, 4] })]
            const stacked = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'stacked' })
            const grouped = createBarScales(series, ['a', 'b'], dimensions, { barLayout: 'grouped' })
            expect(stacked.group).toBeUndefined()
            expect(grouped.group).not.toBeUndefined()
            // Two series so each gets ~half the band, minus padding
            expect(grouped.group!.bandwidth()).toBeLessThan(grouped.band.bandwidth())
        })

        it('uses [0, 1] for the value domain in percent layout', () => {
            const series = [makeSeries({ key: 's1', data: [50, 100, 150] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { barLayout: 'percent' })
            // Linear nice() over [0,1] keeps the domain at [0, 1]
            const yAt1 = value(1)
            const yAt0 = value(0)
            expect(yAt1).toBeLessThan(yAt0)
            expect(value.domain()[0]).toBeCloseTo(0)
            expect(value.domain()[1]).toBeCloseTo(1)
        })
    })

    describe('createBarScales — horizontal orientation', () => {
        it('places bands across the plot height', () => {
            const series = [makeSeries({ key: 's1', data: [10, 20, 30] })]
            const { band } = createBarScales(series, ['a', 'b', 'c'], dimensions, { axisOrientation: 'horizontal' })
            const bandStart = band('a')!
            expect(bandStart).toBeGreaterThanOrEqual(dimensions.plotTop)
            expect(bandStart + band.bandwidth()).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
        })

        it('produces a value scale that increases left-to-right', () => {
            const series = [makeSeries({ key: 's1', data: [0, 50, 100] })]
            const { value } = createBarScales(series, ['a', 'b', 'c'], dimensions, { axisOrientation: 'horizontal' })
            expect(value(100)).toBeGreaterThan(value(0))
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
            // The "30" stack top should map within the plot area
            const yAtStackTop = value(30)
            expect(yAtStackTop).toBeGreaterThanOrEqual(dimensions.plotTop - 1)
            expect(yAtStackTop).toBeLessThanOrEqual(dimensions.plotTop + dimensions.plotHeight + 1)
        })
    })
})
