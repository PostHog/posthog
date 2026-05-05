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

    it('orders derived series CI → main → MA', () => {
        const { result } = renderHook(() =>
            useDerivedSeries(SOURCE, {
                confidenceIntervals: [{ seriesKey: 'a', lower: [0, 1, 2, 3], upper: [2, 3, 4, 5] }],
                movingAverage: [{ seriesKey: 'a', window: 2 }],
            })
        )
        expect(result.current.map((s) => s.key)).toEqual(['a__ci', 'a', 'b', 'a-ma'])
    })

    it('skips derived entries whose seriesKey does not exist in source', () => {
        const { result } = renderHook(() =>
            useDerivedSeries(SOURCE, { movingAverage: [{ seriesKey: 'missing', window: 2 }] })
        )
        expect(result.current.map((s) => s.key)).toEqual(['a', 'b'])
    })
})
