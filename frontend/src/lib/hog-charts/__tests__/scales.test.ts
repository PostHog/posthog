import { autoFormatYTick, computePercentStackData, createXScale, createYScale } from '../core/scales'
import type { ChartDimensions, Series } from '../core/types'

describe('hog-charts scales', () => {
    const dimensions: ChartDimensions = {
        width: 800,
        height: 400,
        plotLeft: 48,
        plotTop: 16,
        plotWidth: 736,
        plotHeight: 352,
    }

    const makeSeries = (data: number[], key = 'test'): Series => ({
        key,
        label: key,
        data,
        color: '#1d4aff',
    })

    describe('createXScale', () => {
        it('creates a point scale over labels', () => {
            const labels = ['Mon', 'Tue', 'Wed', 'Thu']
            const scale = createXScale(labels, dimensions)

            expect(scale.domain()).toEqual(labels)
            expect(scale('Mon')).not.toBeUndefined()
            expect(scale('Thu')).not.toBeUndefined()

            // Points should be within plot range
            const monX = scale('Mon')!
            const thuX = scale('Thu')!
            expect(monX).toBeGreaterThanOrEqual(dimensions.plotLeft)
            expect(thuX).toBeLessThanOrEqual(dimensions.plotLeft + dimensions.plotWidth)
            expect(thuX).toBeGreaterThan(monX)
        })

        it('handles empty labels', () => {
            const scale = createXScale([], dimensions)
            expect(scale.domain()).toEqual([])
        })

        it('handles single label', () => {
            const scale = createXScale(['Only'], dimensions)
            expect(scale('Only')).not.toBeUndefined()
        })
    })

    describe('createYScale', () => {
        it('creates a linear scale with domain from 0 to max', () => {
            const series = [makeSeries([10, 25, 30, 15])]
            const scale = createYScale(series, dimensions)

            // Domain should start at 0 and go to at least 30
            const domain = scale.domain()
            expect(domain[0]).toBe(0)
            expect(domain[1]).toBeGreaterThanOrEqual(30)
        })

        it('includes negative values in domain', () => {
            const series = [makeSeries([-10, 25, 30, -5])]
            const scale = createYScale(series, dimensions)

            const domain = scale.domain()
            expect(domain[0]).toBeLessThanOrEqual(-10)
        })

        it('skips hidden series', () => {
            const series = [
                makeSeries([100, 200, 300], 'visible'),
                { ...makeSeries([1000, 2000, 3000], 'hidden'), hidden: true },
            ]
            const scale = createYScale(series, dimensions)

            const domain = scale.domain()
            expect(domain[1]).toBeLessThan(1000)
        })

        it('creates log scale', () => {
            const series = [makeSeries([1, 10, 100, 1000])]
            const scale = createYScale(series, dimensions, { scaleType: 'log' })

            // Log scale should handle the range
            expect(scale(1)).not.toBeUndefined()
            expect(scale(1000)).not.toBeUndefined()
            expect(scale(1)).toBeGreaterThan(scale(1000)) // Y is inverted
        })

        it('creates percent stack scale with 0-1 domain', () => {
            const series = [makeSeries([10, 20])]
            const scale = createYScale(series, dimensions, { percentStack: true })

            const domain = scale.domain()
            expect(domain[0]).toBe(0)
            expect(domain[1]).toBe(1)
        })

        it('falls back to [0,1] domain when no data', () => {
            const scale = createYScale([], dimensions)
            const domain = scale.domain()
            expect(domain[0]).toBe(0)
            expect(domain[1]).toBe(1)
        })
    })

    describe('computePercentStackData', () => {
        it('normalizes data to 0-1 range', () => {
            const series = [makeSeries([30, 40], 'a'), makeSeries([70, 60], 'b')]
            const labels = ['Mon', 'Tue']
            const result = computePercentStackData(series, labels)

            expect(result.size).toBe(2)
            // Top of stack should be 1.0
            const bData = result.get('b')!
            expect(bData[0]).toBeCloseTo(1, 5)
            expect(bData[1]).toBeCloseTo(1, 5)
        })

        it('skips hidden series', () => {
            const series = [makeSeries([50, 50], 'visible'), { ...makeSeries([50, 50], 'hidden'), hidden: true }]
            const labels = ['Mon', 'Tue']
            const result = computePercentStackData(series, labels)

            expect(result.has('hidden')).toBe(false)
            expect(result.has('visible')).toBe(true)
        })

        it('returns empty map for no visible series', () => {
            const result = computePercentStackData([], ['Mon'])
            expect(result.size).toBe(0)
        })
    })

    describe('autoFormatYTick', () => {
        it.each([
            { value: 0.123, domainMax: 1.5, expected: '0.12' },
            { value: 2.5, domainMax: 4, expected: '2.5' },
            { value: 100, domainMax: 500, expected: '100' },
            { value: 0, domainMax: 10, expected: '0' },
        ])('formats $value with domainMax $domainMax as $expected', ({ value, domainMax, expected }) => {
            expect(autoFormatYTick(value, domainMax)).toBe(expected)
        })
    })
})
