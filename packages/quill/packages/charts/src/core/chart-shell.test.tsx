import { renderHook } from '@testing-library/react'

import { useColoredSeries } from './chart-shell'
import type { ChartTheme, ResolvedSeries, Series } from './types'

const THEME: ChartTheme = { colors: ['#1d4aff'] }

// A host that names a series color with a token (billing's cumulative spend line does) would
// otherwise hand `var(--x)` to ctx.strokeStyle/fillStyle, which keeps the previous style: the line
// draws in the grid color and the hover dot draws background-on-background.
describe('useColoredSeries', () => {
    afterEach(() => {
        document.body.style.removeProperty('--ink')
    })

    function coloredSeries(series: Series[]): ResolvedSeries[] {
        return renderHook(() => useColoredSeries(series, THEME)).result.current
    }

    it('falls back to the theme palette when a series sets no color', () => {
        expect(coloredSeries([{ key: 'a', label: 'A', data: [1] }])[0].color).toBe('#1d4aff')
    })

    it('resolves a variable series color to a concrete color', () => {
        document.body.style.setProperty('--ink', '#111111')
        expect(coloredSeries([{ key: 'a', label: 'A', data: [1], color: 'var(--ink)' }])[0].color).toBe('#111111')
    })

    it('resolves a variable per-bar color to a concrete color', () => {
        document.body.style.setProperty('--ink', '#111111')
        const series: Series[] = [{ key: 'a', label: 'A', data: [1], bars: [{ color: 'var(--ink)' }] }]
        expect(coloredSeries(series)[0].bars?.[0].color).toBe('#111111')
    })
})
