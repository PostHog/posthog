import { fireEvent, render } from '@testing-library/react'

import type { ChartTheme, TooltipContext } from '../../core/types'
import { DefaultTooltip } from '../../overlays/DefaultTooltip'
import { createDefaultTooltipAccessor, ensureJsdom, hoverUntilTooltip, renderChart } from '../../testing'
import { Sparkline } from './Sparkline'

const THEME: ChartTheme = { colors: ['#22d3ee', '#f14f58'], backgroundColor: '#ffffff' }
const LABELS = ['Jan', 'Feb', 'Mar', 'Apr']

describe('Sparkline', () => {
    it('renders a canvas for the line chart', () => {
        const { container } = renderChart(<Sparkline data={[100, 200, 300, 400]} labels={LABELS} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('fires onHoverIndexChange with the hovered index and -1 when leaving', () => {
        const onHover = jest.fn()
        const { chart, container } = renderChart(
            <Sparkline data={[100, 200, 300, 400]} labels={LABELS} theme={THEME} onHoverIndexChange={onHover} />
        )
        // Initial hoverIndex is -1, so the first subscription fire matches the "not hovering" state.
        expect(onHover).toHaveBeenCalledWith(-1)
        onHover.mockClear()

        chart.hoverAtIndex(2)
        expect(onHover).toHaveBeenLastCalledWith(2)

        const wrapper = container.querySelector('canvas')!.parentElement as HTMLElement
        fireEvent.mouseLeave(wrapper)
        expect(onHover).toHaveBeenLastCalledWith(-1)
    })

    it('fires -1 on unmount so a parent still mounted does not show a stale positive index', () => {
        const onHover = jest.fn()
        const { chart, unmount } = renderChart(
            <Sparkline data={[100, 200, 300]} labels={LABELS.slice(0, 3)} theme={THEME} onHoverIndexChange={onHover} />
        )
        chart.hoverAtIndex(1)
        onHover.mockClear()
        unmount()
        expect(onHover).toHaveBeenLastCalledWith(-1)
    })

    it('does not require labels — falls back to index strings', () => {
        const { container } = renderChart(<Sparkline data={[10, 20, 30]} theme={THEME} />)
        expect(container.querySelector('canvas')).not.toBeNull()
    })

    it('renders multi-series stacked bars via the series prop', () => {
        const { chart } = renderChart(
            <Sparkline
                type="bar"
                series={[
                    { key: 'success', label: 'Success', data: [10, 20, 30, 40] },
                    { key: 'failure', label: 'Failure', data: [1, 2, 3, 4] },
                ]}
                labels={LABELS}
                theme={THEME}
            />
        )
        expect(chart.seriesCount).toBe(2)
    })

    it('tooltips a bar the cursor is above, which a bar chart would not', async () => {
        const { chart } = renderChart(
            <Sparkline
                type="bar"
                data={[100, 1, 1, 1]}
                labels={LABELS}
                theme={THEME}
                tooltip={(ctx: TooltipContext) => <DefaultTooltip {...ctx} />}
            />
        )
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 2, LABELS.length))
        expect(tooltip.label()).toBe('Mar')
    })

    it('enables the tooltip when a tooltip render prop is supplied', async () => {
        const { chart } = renderChart(
            <Sparkline
                data={[100, 200, 300, 400]}
                labels={LABELS}
                theme={THEME}
                tooltip={(ctx: TooltipContext) => <DefaultTooltip {...ctx} />}
            />
        )
        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 2, LABELS.length))
        expect(tooltip.label()).toBe('Mar')
    })

    describe('errors', () => {
        beforeEach(() => {
            jest.spyOn(console, 'error').mockImplementation(() => {})
        })
        afterEach(() => {
            jest.mocked(console.error).mockRestore()
        })

        it('reports an error from its inner chart through onError', () => {
            // Only the base `Chart` reads `axisColor`, so the error starts inside the inner chart's own boundary.
            const theme = {
                ...THEME,
                get axisColor(): string {
                    throw new Error('boom')
                },
            } as ChartTheme
            const onError = jest.fn()
            ensureJsdom()
            render(<Sparkline data={[1, 2, 3]} theme={theme} onError={onError} />)
            expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'boom' }), expect.anything())
        })
    })
})
