import { dataColorPalette } from '@posthog/quill-tokens'

import { DEFAULT_CHART_COLORS, themeFromCssVars } from './theme'

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
})
