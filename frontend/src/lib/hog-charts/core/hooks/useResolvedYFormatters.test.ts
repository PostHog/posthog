import { renderHook } from '@testing-library/react'

import type { ChartScales } from '../types'
import { useResolvedYFormatters } from './useResolvedYFormatters'

function makeScales(overrides: Partial<ChartScales> = {}): ChartScales {
    return {
        x: () => 0,
        y: () => 0,
        yTicks: () => [0, 50, 100],
        ...overrides,
    }
}

describe('useResolvedYFormatters', () => {
    it('uses the supplied yTickFormatter for both left and right when provided', () => {
        const fmt = (v: number): string => `custom-${v}`
        const { result } = renderHook(() => useResolvedYFormatters(makeScales(), fmt))
        expect(result.current.left).toBe(fmt)
        expect(result.current.right).toBe(fmt)
    })

    it('returns a working left formatter when scales is null', () => {
        const { result } = renderHook(() => useResolvedYFormatters(null, undefined))
        expect(typeof result.current.left(123)).toBe('string')
    })

    it('returns undefined right formatter when no right axis exists', () => {
        const { result } = renderHook(() => useResolvedYFormatters(makeScales(), undefined))
        expect(result.current.right).toBeUndefined()
    })

    it('returns a right formatter sourced from the right axis ticks', () => {
        const scales = makeScales({
            yAxes: {
                left: { scale: () => 0, ticks: () => [0, 1, 2], position: 'left' },
                right: { scale: () => 0, ticks: () => [0, 1000], position: 'right' },
            },
        })
        const { result } = renderHook(() => useResolvedYFormatters(scales, undefined))
        expect(result.current.right).not.toBeUndefined()
        expect(typeof result.current.right!(500)).toBe('string')
    })
})
