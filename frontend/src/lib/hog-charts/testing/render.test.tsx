import { cleanup } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'

import type { ChartTheme, TooltipContext } from '../core/types'
import { renderHogChart } from './render'

const THEME: ChartTheme = { colors: ['#000'], backgroundColor: '#ffffff', tooltipBackground: '#abcdef' }

const TOOLTIP_CTX: TooltipContext = {
    dataIndex: 0,
    label: 'Mon',
    seriesData: [{ series: { key: 'a', label: 'A', data: [1] }, color: '#f00', value: 1 }],
    position: { x: 0, y: 0 },
    hoverPosition: null,
    canvasBounds: {
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        toJSON: () => ({}),
    } as DOMRect,
    isPinned: false,
}

function ChartWithoutLayoutProvider({
    tooltip,
    theme: _theme,
}: {
    tooltip?: (ctx: TooltipContext) => ReactNode
    theme?: ChartTheme
}): ReactElement {
    // Deliberately omit ChartLayoutContext.Provider — the renderHogChart fallback should supply it.
    return (
        <div>
            <canvas aria-label="Chart with 1 data series" />
            <div data-attr="rendered-tooltip">{tooltip?.(TOOLTIP_CTX)}</div>
        </div>
    )
}

describe('renderHogChart', () => {
    afterEach(() => cleanup())

    it('falls back to a ChartLayoutContext provider so DefaultTooltip renders without an inner provider', () => {
        const { container } = renderHogChart(<ChartWithoutLayoutProvider theme={THEME} />)

        const tooltipWrap = container.querySelector('[data-attr="rendered-tooltip"]')
        expect(tooltipWrap).not.toBeNull()
        // DefaultTooltip reads theme.tooltipBackground via useChartLayout(); if the fallback
        // wasn't installed, useChartLayout would throw and nothing would render here.
        const inner = tooltipWrap!.querySelector('div')
        expect(inner).not.toBeNull()
        expect((inner as HTMLElement).style.backgroundColor).toBe('rgb(171, 205, 239)')
    })

    it('still works when the chart omits the theme prop (defaults to a stub theme)', () => {
        const { container } = renderHogChart(<ChartWithoutLayoutProvider />)
        expect(container.querySelector('[data-attr="rendered-tooltip"]')).not.toBeNull()
    })
})
