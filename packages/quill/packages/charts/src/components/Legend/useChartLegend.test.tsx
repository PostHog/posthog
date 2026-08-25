import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'

import type { ChartTheme, Series } from '../../core/types'
import type { LegendItem } from './Legend'
import { applyHiddenSeries, useChartLegend, type LegendItemControls } from './useChartLegend'

const THEME: ChartTheme = { colors: ['#1f77b4', '#ff7f0e', '#2ca02c'] }

const PLAIN = { additive: false }
const ADDITIVE = { additive: true }

let captured: LegendItemControls | null = null
const captureOne = (node: ReactNode, _item: LegendItem, controls: LegendItemControls): ReactNode => {
    captured = controls
    return node
}

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

    it('hands each row its own controls through config.renderItem', () => {
        const seen: Record<string, LegendItemControls> = {}
        const renderItem = (node: ReactNode, item: LegendItem, controls: LegendItemControls): ReactNode => {
            seen[item.key] = controls
            return node
        }
        const { result } = renderHook(() =>
            useChartLegend(SERIES, THEME, { show: true, defaultHiddenKeys: ['a', 'c'], renderItem })
        )

        result.current.legendProps.items.forEach((item) => result.current.legendProps.renderItem!(null, item))

        expect(seen.a.isHidden).toBe(true)
        expect(seen.b.isHidden).toBe(false)
        expect(seen.b.isOnlyVisible).toBe(true)
        expect(seen.a.isOnlyVisible).toBe(false)
        expect(seen.b.areAllVisible).toBe(false)
        expect(seen.b.canIsolate).toBe(true)

        act(() => seen.b.toggleAll())
        expect(result.current.legendProps.hiddenKeys).toEqual([])
    })

    it('hides every series through toggleAll, then restores them all', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true, renderItem: captureOne }))
        const controls = (): LegendItemControls => {
            result.current.legendProps.renderItem!(null, result.current.legendProps.items[0])
            return captured!
        }

        act(() => controls().toggleAll())
        expect(result.current.legendProps.hiddenKeys).toEqual(['a', 'b', 'c'])

        act(() => controls().toggleAll())
        expect(result.current.legendProps.hiddenKeys).toEqual([])
    })

    it('toggles a series off then back on in uncontrolled mode, keeping it in the legend', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }))

        act(() => result.current.legendProps.onItemClick!('b', ADDITIVE))
        expect(result.current.legendProps.hiddenKeys).toEqual(['b'])
        // Hidden series is excluded for rendering...
        expect(result.current.visibleSeries.find((s) => s.key === 'b')?.visibility?.excluded).toBe(true)
        // ...but still listed in the legend so it can be restored.
        expect(result.current.legendProps.items.map((i) => i.key)).toContain('b')

        act(() => result.current.legendProps.onItemClick!('b', ADDITIVE))
        expect(result.current.legendProps.hiddenKeys).toEqual([])
        expect(result.current.visibleSeries.find((s) => s.key === 'b')?.visibility?.excluded).toBeUndefined()
    })

    it('isolates a series on a plain click, and restores every series on the next one', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }))

        act(() => result.current.legendProps.onItemClick!('b', PLAIN))
        expect(result.current.legendProps.hiddenKeys).toEqual(['a', 'c'])
        // The isolated series still renders; the rest are excluded so the axes rescale to it.
        expect(result.current.visibleSeries.filter((s) => !s.visibility?.excluded).map((s) => s.key)).toEqual(['b'])

        act(() => result.current.legendProps.onItemClick!('b', PLAIN))
        expect(result.current.legendProps.hiddenKeys).toEqual([])
    })

    it('adds to an isolated selection on an additive click without dropping it', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }))

        act(() => result.current.legendProps.onItemClick!('b', PLAIN))
        act(() => result.current.legendProps.onItemClick!('c', ADDITIVE))
        expect(result.current.legendProps.hiddenKeys).toEqual(['a'])
    })

    it('isolates a different series when one is already isolated', () => {
        const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true }))

        act(() => result.current.legendProps.onItemClick!('b', PLAIN))
        act(() => result.current.legendProps.onItemClick!('c', PLAIN))
        expect(result.current.legendProps.hiddenKeys).toEqual(['a', 'b'])
    })

    it('falls back to toggling when there is only one row to isolate', () => {
        const single = [SERIES[0]]
        const { result } = renderHook(() => useChartLegend(single, THEME, { show: true }))

        act(() => result.current.legendProps.onItemClick!('a', PLAIN))
        expect(result.current.legendProps.hiddenKeys).toEqual(['a'])
    })

    describe('rows that share a visibility group', () => {
        // Trends' compare mode: 'a' and 'b' are one series' current and previous rows, so they share
        // one stored visibility bit and must count as one series to isolate against. The group key is
        // deliberately not also a row key, so hiding "the other rows" and hiding "the other groups"
        // can be told apart.
        const GROUP_BY_ROW: Record<string, string> = { a: 'ab', b: 'ab', c: 'c' }
        const visibilityGroupKey = (key: string): string => GROUP_BY_ROW[key]

        it('keeps the whole group visible when one of its rows is isolated', () => {
            const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true, visibilityGroupKey }))

            act(() => result.current.legendProps.onItemClick!('a', PLAIN))
            expect(result.current.legendProps.hiddenKeys).toEqual(['c'])
        })

        it('restores every series when the isolated group is clicked again', () => {
            const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true, visibilityGroupKey }))

            act(() => result.current.legendProps.onItemClick!('a', PLAIN))
            act(() => result.current.legendProps.onItemClick!('a', PLAIN))
            expect(result.current.legendProps.hiddenKeys).toEqual([])
        })

        it('hides every row of a group when a row outside it is isolated', () => {
            const { result } = renderHook(() => useChartLegend(SERIES, THEME, { show: true, visibilityGroupKey }))

            act(() => result.current.legendProps.onItemClick!('c', PLAIN))
            expect(result.current.legendProps.hiddenKeys).toEqual(['a', 'b'])
        })

        it('reads the isolated group as the only visible one', () => {
            const seen: Record<string, LegendItemControls> = {}
            const renderItem = (node: ReactNode, item: LegendItem, controls: LegendItemControls): ReactNode => {
                seen[item.key] = controls
                return node
            }
            const { result } = renderHook(() =>
                useChartLegend(SERIES, THEME, { show: true, visibilityGroupKey, defaultHiddenKeys: ['c'], renderItem })
            )

            result.current.legendProps.items.forEach((item) => result.current.legendProps.renderItem!(null, item))

            expect([seen.a.isOnlyVisible, seen.b.isOnlyVisible, seen.c.isOnlyVisible]).toEqual([true, true, false])
        })

        it('falls back to toggling when every row is in one group', () => {
            const { result } = renderHook(() =>
                useChartLegend(SERIES, THEME, { show: true, visibilityGroupKey: () => 'only' })
            )

            act(() => result.current.legendProps.onItemClick!('a', PLAIN))
            expect(result.current.legendProps.hiddenKeys).toEqual(['a'])
        })
    })

    it('reports the whole next hidden set through onSetHiddenSeries when controlled', () => {
        const onSetHiddenSeries = jest.fn()
        const { result } = renderHook(() =>
            useChartLegend(SERIES, THEME, { show: true, hiddenKeys: [], onSetHiddenSeries })
        )

        act(() => result.current.legendProps.onItemClick!('b', PLAIN))
        expect(onSetHiddenSeries).toHaveBeenCalledWith(['a', 'c'])
        // Controlled: nothing moves until the parent feeds the new keys back in.
        expect(result.current.legendProps.hiddenKeys).toEqual([])
    })

    it('degrades a controlled legend without onSetHiddenSeries to plain toggling', () => {
        const onToggleSeries = jest.fn()
        const { result } = renderHook(() =>
            useChartLegend(SERIES, THEME, { show: true, hiddenKeys: [], onToggleSeries })
        )

        act(() => result.current.legendProps.onItemClick!('b', PLAIN))
        expect(onToggleSeries).toHaveBeenCalledWith('b', true)
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

        act(() => result.current.legendProps.onItemClick!('a', ADDITIVE))
        expect(onToggleSeries).toHaveBeenCalledWith('a', false)
        // Controlled: hiddenKeys is unchanged until the parent updates the prop.
        expect(result.current.legendProps.hiddenKeys).toEqual(['a'])

        act(() => result.current.legendProps.onItemClick!('b', ADDITIVE))
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
