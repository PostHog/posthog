import { renderHook } from '@testing-library/react'

import type { ResolveValueFn, Series } from '../types'
import { useStableResolveValue } from './useStableResolveValue'

const series: Series = { key: 'a', label: 'A', data: [10, NaN, 30] }

describe('useStableResolveValue', () => {
    it('delegates to the supplied resolveValue', () => {
        const fn: ResolveValueFn = (s, i) => s.data[i] * 2
        const { result } = renderHook(() => useStableResolveValue(fn))
        expect(result.current(series, 0)).toBe(20)
        expect(result.current(series, 2)).toBe(60)
    })

    it('falls back to series.data[i] when resolveValue is undefined', () => {
        const { result } = renderHook(() => useStableResolveValue(undefined))
        expect(result.current(series, 0)).toBe(10)
    })

    it('returns 0 for non-finite or non-numeric values when resolveValue is undefined', () => {
        const { result } = renderHook(() => useStableResolveValue(undefined))
        expect(result.current(series, 1)).toBe(0)
        const weird: Series = { key: 'b', label: 'B', data: [Infinity, -Infinity] }
        expect(result.current(weird, 0)).toBe(0)
        expect(result.current(weird, 1)).toBe(0)
    })

    it('keeps callback identity stable across resolveValue changes', () => {
        const first: ResolveValueFn = (s, i) => s.data[i]
        const second: ResolveValueFn = (s, i) => s.data[i] * 100
        const { result, rerender } = renderHook(({ fn }: { fn: ResolveValueFn }) => useStableResolveValue(fn), {
            initialProps: { fn: first },
        })
        const initial = result.current
        rerender({ fn: second })
        expect(result.current).toBe(initial)
        expect(result.current(series, 0)).toBe(1000)
    })
})
