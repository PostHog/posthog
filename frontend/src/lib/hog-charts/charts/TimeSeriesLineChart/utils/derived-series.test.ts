import type { Series } from '../../../core/types'
import {
    applyComparisonDimming,
    buildConfidenceIntervalSeries,
    buildMovingAverageSeries,
    buildTrendLineSeries,
} from './derived-series'

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
        // Centered moving average — middle value averages the surrounding points.
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
    it('builds a linear-fit dotted series at reduced opacity', () => {
        const tl = buildTrendLineSeries({ sourceSeries: SOURCE, kind: 'linear' })
        expect(tl.key).toBe('visits__trendline')
        expect(tl.label).toBe('Visits')
        // Source is a perfect linear ramp, so the fit should match.
        expect(tl.data).toEqual([10, 12, 14, 16, 18, 20, 22])
        expect(tl.color).toMatch(/^rgba\(/)
        expect(tl.stroke?.pattern).toEqual([1, 3])
        expect(tl.visibility?.fromStack).toBe(true)
    })

    it('falls back to linear for exponential when values are non-positive', () => {
        const negative: Series = { ...SOURCE, key: 'neg', data: [-1, 0, 1, 2] }
        const tl = buildTrendLineSeries({ sourceSeries: negative, kind: 'exponential' })
        expect(tl.data).toHaveLength(4)
        expect(tl.data.every(Number.isFinite)).toBe(true)
    })

    it('produces an exponential fit when all values are positive', () => {
        // y = 2^x — log-linear in x, so the fit should recover the input.
        const expSource: Series = { ...SOURCE, key: 'exp', data: [1, 2, 4, 8, 16, 32, 64] }
        const tl = buildTrendLineSeries({ sourceSeries: expSource, kind: 'exponential' })
        expect(tl.data[0]).toBeCloseTo(1, 4)
        expect(tl.data[6]).toBeCloseTo(64, 2)
    })
})

describe('applyComparisonDimming', () => {
    const A: Series = { key: 'a', label: 'A', data: [1, 2], color: '#112233' }
    const A_PREV: Series = { key: 'a-prev', label: 'A (prev)', data: [1, 2], color: '#112233' }
    const B: Series = { key: 'b', label: 'B', data: [3, 4], color: '#445566' }

    it('returns the same reference when comparisonOf is undefined', () => {
        const series = [A, B]
        expect(applyComparisonDimming(series, undefined)).toBe(series)
    })

    it('returns the same reference when comparisonOf is empty', () => {
        const series = [A, B]
        expect(applyComparisonDimming(series, {})).toBe(series)
    })

    it('rewrites comparison series to a dimmed rgba colour, leaves primaries alone', () => {
        const result = applyComparisonDimming([A, A_PREV, B], { 'a-prev': 'a' })
        expect(result[0]).toBe(A)
        expect(result[2]).toBe(B)
        expect(result[1].color).toMatch(/^rgba\([^)]*,\s*0\.5\)$/)
    })

    it('leaves non-hex colours untouched (no double-wrapping)', () => {
        const rgbaSource: Series = { key: 'a-prev', label: '', data: [], color: 'rgba(0,0,0,1)' }
        const result = applyComparisonDimming([rgbaSource], { 'a-prev': 'a' })
        expect(result[0].color).toBe('rgba(0,0,0,1)')
    })
})
