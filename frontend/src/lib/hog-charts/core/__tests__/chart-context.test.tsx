import { act, cleanup, render } from '@testing-library/react'
import React, { useState } from 'react'

import { ChartHoverContext, ChartLayoutContext, useChart, useChartHover, useChartLayout } from '../chart-context'
import type { ChartLayoutContextValue } from '../chart-context'
import type { ChartTheme } from '../types'

const THEME: ChartTheme = { colors: ['#000'], backgroundColor: '#ffffff' }

const LAYOUT: ChartLayoutContextValue = {
    dimensions: { width: 100, height: 100, plotLeft: 0, plotTop: 0, plotWidth: 100, plotHeight: 100 },
    labels: ['A', 'B'],
    series: [],
    scales: { x: () => 0, y: () => 0, yTicks: () => [] },
    theme: THEME,
    resolveValue: (s, i) => s.data[i] ?? 0,
    canvasBounds: () => null,
}

describe('chart-context split', () => {
    afterEach(() => cleanup())

    it('does not re-render memoized layout consumers when only hoverIndex changes', () => {
        const layoutRenderCount = { current: 0 }
        const hoverRenderCount = { current: 0 }

        const LayoutConsumer = React.memo(function LayoutConsumer(): React.ReactElement {
            useChartLayout()
            layoutRenderCount.current += 1
            return <div data-testid="layout" />
        })

        const HoverConsumer = React.memo(function HoverConsumer(): React.ReactElement {
            const { hoverIndex } = useChartHover()
            hoverRenderCount.current += 1
            return <div data-testid="hover">{hoverIndex}</div>
        })

        let setHover: (n: number) => void = () => {}
        function Harness(): React.ReactElement {
            const [hoverIndex, _setHover] = useState(-1)
            setHover = _setHover
            return (
                <ChartLayoutContext.Provider value={LAYOUT}>
                    <ChartHoverContext.Provider value={{ hoverIndex }}>
                        <LayoutConsumer />
                        <HoverConsumer />
                    </ChartHoverContext.Provider>
                </ChartLayoutContext.Provider>
            )
        }

        render(<Harness />)
        const layoutBefore = layoutRenderCount.current
        const hoverBefore = hoverRenderCount.current

        act(() => setHover(0))
        act(() => setHover(1))
        act(() => setHover(2))

        expect(layoutRenderCount.current).toBe(layoutBefore)
        expect(hoverRenderCount.current).toBeGreaterThan(hoverBefore)
    })

    it('re-renders useChart() consumers on hover (back-compat)', () => {
        const renderCount = { current: 0 }

        function Consumer(): React.ReactElement {
            const ctx = useChart()
            renderCount.current += 1
            return <div data-testid="consumer">{ctx.hoverIndex}</div>
        }

        let setHover: (n: number) => void = () => {}
        function Harness(): React.ReactElement {
            const [hoverIndex, _setHover] = useState(-1)
            setHover = _setHover
            return (
                <ChartLayoutContext.Provider value={LAYOUT}>
                    <ChartHoverContext.Provider value={{ hoverIndex }}>
                        <Consumer />
                    </ChartHoverContext.Provider>
                </ChartLayoutContext.Provider>
            )
        }

        render(<Harness />)
        const before = renderCount.current

        act(() => setHover(5))

        expect(renderCount.current).toBeGreaterThan(before)
    })

    it('useChartLayout throws when used outside a chart', () => {
        function Consumer(): React.ReactElement {
            useChartLayout()
            return <div />
        }

        const spy = jest.spyOn(console, 'error').mockImplementation(() => {})
        expect(() => render(<Consumer />)).toThrow(/useChartLayout must be used inside a chart/)
        spy.mockRestore()
    })
})
