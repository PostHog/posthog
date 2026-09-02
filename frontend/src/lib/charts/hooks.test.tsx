import { act, cleanup, renderHook } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { useChartTheme } from './hooks'

const AXIS_LABEL_VAR = '--color-graph-axis-label'

describe('useChartTheme', () => {
    beforeEach(() => initKeaTests())

    afterEach(() => {
        cleanup()
        document.body.removeAttribute('theme')
        document.body.style.removeProperty(AXIS_LABEL_VAR)
    })

    // The theme is applied from an effect in `useThemedHtml`, so the attribute lands after the render
    // that requested it. Read the variables during that render and every chart keeps the outgoing
    // theme's axis color until the page reloads.
    it('re-reads CSS variables after the theme attribute is written', async () => {
        document.body.style.setProperty(AXIS_LABEL_VAR, '#111111')
        const { result } = renderHook(() => useChartTheme())
        expect(result.current.axisColor).toBe('#111111')

        await act(async () => {
            document.body.style.setProperty(AXIS_LABEL_VAR, '#eeeeee')
            document.body.setAttribute('theme', 'dark')
        })

        expect(result.current.axisColor).toBe('#eeeeee')
    })
})
