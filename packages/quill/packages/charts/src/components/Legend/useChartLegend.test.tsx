import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'

import type { ChartTheme, Series } from '../../core/types'
import { applyHiddenSeries, useChartLegend } from './useChartLegend'

const THEME: ChartTheme = { colors: ['#1f77b4', '#ff7f0e', '#2ca02c'] }

const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3] },
    { key: 'b', label: 'B', data: [4, 5, 6] },
    { key: 'c', label: 'C', data: [7, 8, 9] },
]

describe('useChartLegend', () => {
    describe('applyHiddenSeries', () => {
        it('returns the same array reference when nothing is hidden', () => {
            expect(applyHiddenSeries(SERIES, new Set())).toBe(SERIES)
        })

        it('marks only hidden keys excluded and preserves other visibility flags', () => {
            const series: Series[] = [
                {
                    key: 'a',
                    label: 'A',
                    data: [1],
                    visibility: { tooltip: false },
                },
                { key: 'b', label: 'B', data: [2] },
            ]
            const result = applyHiddenSeries(series, new Set(['a']))
            expect(result[0].visibility).toEqual({
                tooltip: false,
                excluded: true,
            })
            expect(result[1].visibility).toBeUndefined()
        })
    })

    it('derives a legend item per series, listing every series', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }))
        expect(result.current.legendProps.items.map((i) => i.key)).toEqual(['a', 'b', 'c'])
        expect(result.current.legendProps.show).toBe(true)
    })

    it('forwards config.renderItem onto legendProps', () => {
        const renderItem = (node: ReactNode): ReactNode => node
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true, renderItem }))
        expect(result.current.legendProps.renderItem).toBe(renderItem)
    })

    it('toggles a series off then back on in uncontrolled mode, keeping it in the legend', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }))

        act(() => result.current.legendProps.onItemClick!('b'))
        expect(result.current.legendProps.hiddenKeys).toEqual(['b'])
        // Hidden series is excluded for rendering...
        expect(result.current.visibleSeries.find((s) => s.key === 'b')?.visibility?.excluded).toBe(true)
        // ...but still listed in the legend so it can be restored.
        expect(result.current.legendProps.items.map((i) => i.key)).toContain('b')

        act(() => result.current.legendProps.onItemClick!('b'))
        expect(result.current.legendProps.hiddenKeys).toEqual([])
        expect(result.current.visibleSeries.find((s) => s.key === 'b')?.visibility?.excluded).toBeUndefined()
    })

    it('honors defaultHiddenKeys for the initial uncontrolled state', () => {
        const { result } = renderHook(() =>
            useChartLegend(SERIES, THEME, {
                show: true,
                defaultHiddenKeys: ['c'],
            })
        )
        expect(result.current.legendProps.hiddenKeys).toEqual(['c'])
        expect(result.current.visibleSeries.find((s) => s.key === 'c')?.visibility?.excluded).toBe(true)
    })

    it('does not mutate its own state in controlled mode — only notifies onToggleSeries', () => {
        const onToggleSeries = jest.fn()
        const { result } = renderHook(() =>
            useChartLegend(SERIES, THEME, {
                show: true,
                hiddenKeys: ['a'],
                onToggleSeries,
            })
        )
        expect(result.current.legendProps.hiddenKeys).toEqual(['a'])

        act(() => result.current.legendProps.onItemClick!('a'))
        expect(onToggleSeries).toHaveBeenCalledWith('a', false)
        // Controlled: hiddenKeys is unchanged until the parent updates the prop.
        expect(result.current.legendProps.hiddenKeys).toEqual(['a'])

        act(() => result.current.legendProps.onItemClick!('b'))
        expect(onToggleSeries).toHaveBeenCalledWith('b', true)
    })

    it('omits onItemClick when interactive is false (static legend)', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true, interactive: false }))
        expect(result.current.legendProps.onItemClick).toBeUndefined()
    })

    it('uses caller-supplied items verbatim when provided', () => {
        const items = [{ key: 'a', label: 'Custom A', color: '#000' }]
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }, items))
        expect(result.current.legendProps.items).toBe(items)
    })
})
