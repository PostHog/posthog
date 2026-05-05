import { renderHook } from '@testing-library/react'

import type { Series } from '../../../core/types'
import { useDerivedSeries } from './use-derived-series'

const SOURCE: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3, 4], color: '#112233' },
    { key: 'b', label: 'B', data: [5, 6, 7, 8], color: '#445566' },
]

describe('useDerivedSeries', () => {
    it('returns the source reference unchanged when no options are set', () => {
        const { result } = renderHook(() => useDerivedSeries(SOURCE, {}))
        expect(result.current).toBe(SOURCE)
    })

    it('orders derived series CI → main → MA → trend lines', () => {
        const { result } = renderHook(() =>
            useDerivedSeries(SOURCE, {
                confidenceIntervals: [{ seriesKey: 'a', lower: [0, 1, 2, 3], upper: [2, 3, 4, 5] }],
                movingAverage: [{ seriesKey: 'a', window: 2 }],
                trendLines: [{ seriesKey: 'a', kind: 'linear' }],
            })
        )
        expect(result.current.map((s) => s.key)).toEqual(['a__ci', 'a', 'b', 'a-ma', 'a__trendline'])
    })

    it('skips derived entries whose seriesKey does not exist in source', () => {
        const { result } = renderHook(() =>
            useDerivedSeries(SOURCE, { movingAverage: [{ seriesKey: 'missing', window: 2 }] })
        )
        expect(result.current.map((s) => s.key)).toEqual(['a', 'b'])
    })

    it('applies comparison dimming as the final pass', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [1, 2], color: '#112233' },
            { key: 'a-prev', label: 'A (prev)', data: [1, 2], color: '#112233' },
        ]
        const { result } = renderHook(() => useDerivedSeries(series, { comparisonOf: { 'a-prev': 'a' } }))
        expect(result.current[0].color).toBe('#112233')
        expect(result.current[1].color).toMatch(/^rgba\([^)]*,\s*0\.5\)$/)
    })

    it('resolves a trendline whose seriesKey targets a moving-average series', () => {
        const { result } = renderHook(() =>
            useDerivedSeries(SOURCE, {
                movingAverage: [{ seriesKey: 'a', window: 2 }],
                trendLines: [{ seriesKey: 'a-ma', kind: 'linear' }],
            })
        )
        // Order: source (a, b) → MA (a-ma) → trendline of MA (a-ma__trendline)
        expect(result.current.map((s) => s.key)).toEqual(['a', 'b', 'a-ma', 'a-ma__trendline'])
    })

    it('threads fitUpTo from the trendLines config into the regression fit', () => {
        // Constrained fit over [0, 4) stays flat near 10; unconstrained fit slopes up.
        const data = [10, 10, 10, 10, 100, 100]
        const source: Series[] = [{ key: 'a', label: 'A', data, color: '#112233' }]
        const { result: fitted } = renderHook(() =>
            useDerivedSeries(source, { trendLines: [{ seriesKey: 'a', kind: 'linear', fitUpTo: 4 }] })
        )
        const { result: full } = renderHook(() =>
            useDerivedSeries(source, { trendLines: [{ seriesKey: 'a', kind: 'linear' }] })
        )
        const fittedTrend = fitted.current.find((s) => s.key === 'a__trendline')!.data
        const fullTrend = full.current.find((s) => s.key === 'a__trendline')!.data
        const fittedDeviationFromTen = fittedTrend.map((v) => Math.abs(v - 10))
        const fittedLast = fittedTrend[fittedTrend.length - 1]
        const fullLast = fullTrend[fullTrend.length - 1]
        expect(Math.max(...fittedDeviationFromTen)).toBeLessThan(1e-6)
        expect(fullLast).toBeGreaterThan(fittedLast)
    })

    it('busts the memo cache when fitUpTo changes between renders', () => {
        const data = [10, 10, 10, 10, 100, 100]
        const source: Series[] = [{ key: 'a', label: 'A', data, color: '#112233' }]
        const { result, rerender } = renderHook(
            ({ fitUpTo }: { fitUpTo: number | undefined }) =>
                useDerivedSeries(source, { trendLines: [{ seriesKey: 'a', kind: 'linear', fitUpTo }] }),
            { initialProps: { fitUpTo: 4 as number | undefined } }
        )
        const constrained = result.current.find((s) => s.key === 'a__trendline')!.data.slice()
        rerender({ fitUpTo: undefined })
        const unconstrained = result.current.find((s) => s.key === 'a__trendline')!.data
        expect(unconstrained[unconstrained.length - 1]).toBeGreaterThan(constrained[constrained.length - 1])
    })
})
