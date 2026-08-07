import { act, cleanup, renderHook } from '@testing-library/react'

import { CUSTOM_THEME_STYLES_ID } from 'lib/hooks/useAppliedThemeValue'

import { useChartCssVarTheme } from './hooks'

const AXIS_LABEL_VAR = '--color-graph-axis-label'

describe('useChartCssVarTheme', () => {
    afterEach(() => {
        cleanup()
        document.body.removeAttribute('theme')
        document.body.style.removeProperty(AXIS_LABEL_VAR)
        document.getElementById(CUSTOM_THEME_STYLES_ID)?.remove()
    })

    // The app applies a theme from an effect in `useThemedHtml`, so the DOM changes after the render
    // that requested it. Both of these leave charts on the outgoing theme's colors if the hook reads
    // computed styles during render instead of watching for the change.
    it.each([
        ['the theme attribute is written', (): void => document.body.setAttribute('theme', 'dark')],
        [
            'a custom theme stylesheet is injected',
            (): void => {
                const style = document.createElement('style')
                style.id = CUSTOM_THEME_STYLES_ID
                document.head.appendChild(style)
            },
        ],
    ])('re-reads CSS variables after %s', async (_, applyTheme) => {
        document.body.style.setProperty(AXIS_LABEL_VAR, '#111111')
        const { result } = renderHook(() => useChartCssVarTheme())
        expect(result.current.axisColor).toBe('#111111')

        await act(async () => {
            document.body.style.setProperty(AXIS_LABEL_VAR, '#eeeeee')
            applyTheme()
        })

        expect(result.current.axisColor).toBe('#eeeeee')
    })
})
