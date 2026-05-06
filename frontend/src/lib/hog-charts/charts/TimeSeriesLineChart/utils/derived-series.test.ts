import type { Series } from '../../../core/types'
import { buildConfidenceIntervalSeries, buildMovingAverageSeries, buildTrendLineSeries } from './derived-series'

const SOURCE: Series = {
    key: 'visits',
    label: 'Visits',
    data: [10, 12, 14, 16, 18, 20, 22],
    color: '#336699',
    yAxisId: 'y1',
    meta: { domain: 'visits' },
}

describe('buildConfidenceIntervalSeries', () => {
    it('returns a fill-between series keyed off the source seriesKey', () => {
        const ci = buildConfidenceIntervalSeries({
            seriesKey: SOURCE.key,
            label: SOURCE.label,
            baseColor: SOURCE.color,
            lower: [9, 11, 13, 15, 17, 19, 21],
            upper: [11, 13, 15, 17, 19, 21, 23],
            yAxisId: SOURCE.yAxisId,
            meta: SOURCE.meta,
        })
        expect(ci.key).toBe('visits__ci')
        expect(ci.label).toBe('Visits (CI)')
        expect(ci.data).toEqual([11, 13, 15, 17, 19, 21, 23])
        expect(ci.color).toBe('#336699')
        expect(ci.yAxisId).toBe('y1')
        expect(ci.meta).toEqual({ domain: 'visits' })
        expect(ci.fill?.lowerData).toEqual([9, 11, 13, 15, 17, 19, 21])
        expect(ci.fill?.opacity).toBeGreaterThan(0)
        expect(ci.visibility?.fromTooltip).toBe(true)
        expect(ci.visibility?.fromValueLabels).toBe(true)
    })

    it('forwards the excluded flag so an excluded source hides the band', () => {
        const ci = buildConfidenceIntervalSeries({
            seriesKey: 'a',
            label: 'A',
            lower: [0],
            upper: [1],
            excluded: true,
        })
        expect(ci.visibility?.excluded).toBe(true)
    })
})

describe('buildMovingAverageSeries', () => {
    it('computes via movingAverage and styles a dashed overlay', () => {
        const ma = buildMovingAverageSeries({ sourceSeries: SOURCE, window: 3 })
        expect(ma.key).toBe('visits-ma')
        expect(ma.label).toBe('Visits (Moving avg)')
        expect(ma.data).toHaveLength(SOURCE.data.length)
        expect(ma.data[3]).toBeCloseTo((14 + 16 + 18) / 3, 5)
        expect(ma.color).toBe(SOURCE.color)
        expect(ma.yAxisId).toBe(SOURCE.yAxisId)
        expect(ma.stroke?.pattern).not.toBeUndefined()
        expect(ma.visibility?.fromStack).toBe(true)
        expect(ma.visibility?.fromTooltip).toBe(true)
    })

    it('uses an explicit label when provided', () => {
        const ma = buildMovingAverageSeries({ sourceSeries: SOURCE, window: 3, label: 'Smoothed' })
        expect(ma.label).toBe('Smoothed')
    })
})

describe('buildTrendLineSeries', () => {
    it('keys, labels, and styles a dotted dimmed overlay', () => {
        const tl = buildTrendLineSeries({ sourceSeries: SOURCE, kind: 'linear' })
        expect(tl.key).toBe('visits__trendline')
        expect(tl.label).toBe('Visits')
        expect(tl.color).toMatch(/^rgba\(/)
        expect(tl.stroke?.pattern).toEqual([1, 3])
        expect(tl.visibility?.fromStack).toBe(true)
    })

    it.each([
        ['linear', [10, 12, 14, 16, 18, 20, 22], 'linear', undefined, 10, 22],
        ['exponential, all positive (y=2^x)', [1, 2, 4, 8, 16, 32, 64], 'exponential', undefined, 1, 64],
        ['exponential, non-positive falls back to linear y=x-1', [-1, 0, 1, 2], 'exponential', undefined, -1, 2],
        ['exponential, zero in tail with fitUpTo skipping it', [1, 2, 4, 8, 0], 'exponential', 4, 1, 16],
    ] as const)('fits %s', (_label, data, kind, fitUpTo, expectedFirst, expectedLast) => {
        const tl = buildTrendLineSeries({ sourceSeries: { ...SOURCE, data: [...data] }, kind, fitUpTo })
        expect(tl.data).toHaveLength(data.length)
        expect(tl.data.every(Number.isFinite)).toBe(true)
        expect(tl.data[0]).toBeCloseTo(expectedFirst, 2)
        expect(tl.data[data.length - 1]).toBeCloseTo(expectedLast, 2)
    })
})
