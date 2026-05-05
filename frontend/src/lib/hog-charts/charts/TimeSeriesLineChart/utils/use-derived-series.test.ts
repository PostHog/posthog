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
})
