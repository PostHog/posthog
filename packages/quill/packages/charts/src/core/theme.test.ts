import { dataColorPalette } from '@posthog/quill-tokens'

import { chartChromeFromCssVars, DEFAULT_CHART_COLORS, themeFromCssVars } from './theme'

describe('chart theme', () => {
    afterEach(() => {
        document.body.replaceChildren()
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
        // No ink color on this root, so the grid falls back to the graph token.
        expect(theme.gridColor).toBe('#bbbbbb')
        expect(theme.backgroundColor).toBe('#f0f0f0')
    })

    describe('chrome', () => {
        // The grid, the axis line and the crosshair are three different weights of the same ink.
        // Collapsing any two of them — or dropping `axisLineColor`, which no token supplies — makes
        // the axis indistinguishable from the grid it frames.
        it('derives three distinct ink shares from the foreground color', () => {
            const root = rootWithVars({ '--foreground': 'rgb(0, 0, 0)' })

            const chrome = chartChromeFromCssVars({ root })

            expect(chrome.gridColor).toBe('color-mix(in oklab, rgb(0, 0, 0) 6%, transparent)')
            expect(chrome.axisLineColor).toBe('color-mix(in oklab, rgb(0, 0, 0) 35%, transparent)')
            expect(chrome.crosshairColor).toBe('color-mix(in oklab, rgb(0, 0, 0) 22%, transparent)')
        })

        it('dashes the grid and the crosshair even with no ink color to mix', () => {
            // A host with no tokens loaded still gets the dashes: they are mode-independent, so
            // there is nothing to resolve and no reason to fall back.
            const chrome = chartChromeFromCssVars({ root: rootWithVars({}) })

            expect(chrome.gridDashPattern).toEqual([3, 3])
            expect(chrome.crosshairDashPattern).toEqual([3, 3])
        })

        it('ships with the full theme, so a host reading it needs no chrome of its own', () => {
            const theme = themeFromCssVars({ root: rootWithVars({ '--foreground': 'rgb(0, 0, 0)' }) })

            expect(theme.axisLineColor).toBe('color-mix(in oklab, rgb(0, 0, 0) 35%, transparent)')
            expect(theme.gridDashPattern).toEqual([3, 3])
        })
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
})
