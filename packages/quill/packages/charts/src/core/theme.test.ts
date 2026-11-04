import { act, cleanup, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'

import { dataColorPalette } from '@posthog/quill-tokens'

import {
    ChartThemeProvider,
    DEFAULT_CHART_COLORS,
    type ThemeFromCssOptions,
    themeFromCssVars,
    useChartTheme,
    useResolvedChartTheme,
} from './theme'
import type { ChartTheme } from './types'

describe('chart theme', () => {
    afterEach(() => {
        // Unmount first, so the resets below don't fire a live observer outside act().
        cleanup()
        jest.restoreAllMocks()
        document.body.replaceChildren()
        document.body.removeAttribute('style')
        document.documentElement.removeAttribute('class')
    })

    function rootWithVars(vars: Record<string, string>): HTMLElement {
        const el = document.createElement('div')
        for (const [name, value] of Object.entries(vars)) {
            el.style.setProperty(name, value)
        }
        document.body.appendChild(el)
        return el
    }

    it('fallback palette stays in sync with the quill-tokens palette', () => {
        // Guards the duplicated literal against drift — tokens (`dataColorPalette`)
        // is the source of truth; update both together.
        expect(DEFAULT_CHART_COLORS).toEqual([...dataColorPalette])
    })

    it('reads --data-color-* and quill chrome vars off the given root', () => {
        const root = rootWithVars({
            '--data-color-1': '#111111',
            '--data-color-2': '#222222',
            '--color-graph-axis-label': '#aaaaaa',
            '--color-graph-axis-line': '#bbbbbb',
            '--background': '#f0f0f0',
        })

        const theme = themeFromCssVars({ root, colorCount: 2 })

        expect(theme.colors).toEqual(['#111111', '#222222'])
        expect(theme.axisColor).toBe('#aaaaaa')
        expect(theme.gridColor).toBe('#bbbbbb')
        expect(theme.backgroundColor).toBe('#f0f0f0')
    })

    it.each<{ name: string; vars: Record<string, string>; expected: string }>([
        {
            name: 'prefers the quill token over the app compat name',
            vars: { '--background': '#quill0', '--color-bg-surface-primary': '#app000' },
            expected: '#quill0',
        },
        {
            name: 'falls back to the app compat name when the quill token is absent',
            vars: { '--color-bg-surface-primary': '#app000' },
            expected: '#app000',
        },
    ])('backgroundColor $name', ({ vars, expected }) => {
        const root = rootWithVars(vars)

        expect(themeFromCssVars({ root }).backgroundColor).toBe(expected)
    })

    it('falls back to DEFAULT_CHART_COLORS for unset color vars', () => {
        const root = rootWithVars({})

        expect(themeFromCssVars({ root }).colors).toEqual([...DEFAULT_CHART_COLORS])
    })

    it('wraps the fallback palette when colorCount exceeds the defaults', () => {
        const root = rootWithVars({})
        const colorCount = DEFAULT_CHART_COLORS.length + 2

        const { colors } = themeFromCssVars({ root, colorCount })

        expect(colors).toHaveLength(colorCount)
        expect(colors[DEFAULT_CHART_COLORS.length]).toBe(DEFAULT_CHART_COLORS[0])
    })

    const PROP_THEME: ChartTheme = { colors: ['#000001'] }
    const PROVIDED_THEME: ChartTheme = { colors: ['#000002'] }

    it.each([
        { name: 'the prop over the provider', prop: PROP_THEME, provided: PROVIDED_THEME, expected: '#000001' },
        { name: 'the provider without a prop', prop: undefined, provided: PROVIDED_THEME, expected: '#000002' },
        { name: 'the CSS vars without either', prop: undefined, provided: null, expected: '#000003' },
    ])('resolves a chart theme from $name', ({ prop, provided, expected }) => {
        document.body.style.setProperty('--data-color-1', '#000003')
        const wrapper = ({ children }: { children: ReactNode }): ReactNode =>
            provided ? createElement(ChartThemeProvider, { value: provided }, children) : children
        const { result } = renderHook(() => useResolvedChartTheme(prop), { wrapper })
        expect(result.current.colors[0]).toBe(expected)
        document.body.style.removeProperty('--data-color-1')
    })

    function renderThemeHooks(
        count: number,
        options: ThemeFromCssOptions = {}
    ): { hooks: { result: { current: ChartTheme }; unmount: () => void }[]; renders: () => number } {
        let renders = 0
        const hooks = Array.from({ length: count }, () =>
            renderHook(() => {
                renders++
                return useChartTheme(options)
            })
        )
        return { hooks, renders: () => renders }
    }

    it('shares one observer and one theme object across hook instances', () => {
        const observe = jest.spyOn(MutationObserver.prototype, 'observe')

        const { hooks } = renderThemeHooks(5)

        expect(observe.mock.calls.filter(([target]) => target === document.documentElement)).toHaveLength(1)
        expect(new Set(hooks.map((hook) => hook.result.current)).size).toBe(1)
    })

    it.each([
        { name: 'keeps the object and skips renders when the vars are unchanged', nextColor: null },
        { name: 'gives every caller one new object when a var changes', nextColor: '#222222' },
    ])('on an html class change, $name', async ({ nextColor }) => {
        document.body.style.setProperty('--data-color-1', '#111111')
        const { hooks, renders } = renderThemeHooks(3)
        const before = hooks[0].result.current
        const rendersBefore = renders()

        await act(async () => {
            if (nextColor) {
                document.body.style.setProperty('--data-color-1', nextColor)
            }
            document.documentElement.classList.toggle('some-unrelated-class')
        })

        const after = hooks.map((hook) => hook.result.current)
        expect(new Set(after).size).toBe(1)
        expect(after[0].colors[0]).toBe(nextColor ?? '#111111')
        expect(after[0] === before).toBe(!nextColor)
        expect(renders() - rendersBefore).toBe(nextColor ? hooks.length : 0)
    })

    it('disconnects after the last unmount and re-reads on the next mount', () => {
        const disconnect = jest.spyOn(MutationObserver.prototype, 'disconnect')
        document.body.style.setProperty('--data-color-1', '#111111')
        const { hooks } = renderThemeHooks(3)

        hooks.forEach((hook) => hook.unmount())
        expect(disconnect).toHaveBeenCalledTimes(1)

        document.body.style.setProperty('--data-color-1', '#222222')
        expect(renderThemeHooks(1).hooks[0].result.current.colors[0]).toBe('#222222')
    })

    it('keeps a separate theme per root and colorCount', () => {
        const root = rootWithVars({ '--data-color-1': '#333333' })

        const [byDefault, byCount, byRoot] = [{}, { colorCount: 2 }, { root }].map(
            (options) => renderThemeHooks(1, options).hooks[0].result.current
        )

        expect(byDefault.colors).toHaveLength(DEFAULT_CHART_COLORS.length)
        expect(byCount.colors).toHaveLength(2)
        expect(byRoot.colors[0]).toBe('#333333')
    })
})
