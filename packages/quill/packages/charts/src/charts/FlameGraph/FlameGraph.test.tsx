import { fireEvent } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart, waitForHogChartTooltip } from '../../testing'
import { FlameGraph } from './FlameGraph'
import type { FlameGraphProps, FlameNode } from './types'

const THEME: ChartTheme = {
    colors: ['#1d4aff', '#621da6', '#42827e', '#ce0e74', '#f14f58'],
    backgroundColor: '#ffffff',
}

// The mocked wrapper is 800px wide and rows are 22px tall, so row `d` is centered on y = 22d + 11.
const rowY = (depth: number): number => depth * 22 + 11

const TREE: FlameNode = {
    name: 'root',
    value: 100,
    children: [
        { name: 'a', value: 60, children: [{ name: 'a1', value: 30 }] },
        { name: 'b', value: 30 },
    ],
}

function renderFlame(props: Partial<FlameGraphProps> = {}): ReturnType<typeof renderHogChart> {
    return renderHogChart(<FlameGraph data={TREE} theme={THEME} {...props} />, { nativeTooltip: true })
}

describe('FlameGraph', () => {
    let matchMedia: typeof window.matchMedia | undefined

    beforeAll(() => {
        // Reduced motion snaps the zoom, so a click settles without stepping through animation frames.
        matchMedia = window.matchMedia
        window.matchMedia = ((query: string) => ({ matches: query.includes('reduce') })) as typeof window.matchMedia
    })

    afterAll(() => {
        window.matchMedia = matchMedia as typeof window.matchMedia
    })

    it.each([
        {
            label: 'total, self and shares',
            data: TREE,
            point: [200, rowY(1)],
            expected: ['a', 'Total60 (60%)', 'Self30', 'Of parent60%', 'Click to zoom in'],
        },
        {
            label: 'the change against the baseline',
            data: { ...TREE, value: 130, baselineValue: 100, count: 40, baselineCount: 50 },
            point: [400, rowY(0)],
            expected: ['root', 'Count40', 'Baseline100', 'Change+30%'],
        },
    ])('shows $label in the tooltip of the hovered node', async ({ data, point, expected }) => {
        const { chart } = renderFlame({ data })
        fireEvent.mouseMove(chart.element, { clientX: point[0], clientY: point[1] })
        const tooltip = await waitForHogChartTooltip()
        for (const text of expected) {
            expect(tooltip.textContent).toContain(text)
        }
    })

    it('zooms into a clicked node, reports it, and zooms back out with Escape and reset', () => {
        const onNodeClick = jest.fn()
        const onFocusChange = jest.fn()
        const { chart, getByText } = renderFlame({ onNodeClick, onFocusChange })
        expect(chart.flameBreadcrumb()).toEqual(['All'])

        fireEvent.click(chart.element, { clientX: 200, clientY: rowY(1) })
        expect(chart.flameBreadcrumb()).toEqual(['All', 'root', 'a'])
        expect(onNodeClick).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'root/a', value: 60, self: 30, fractionOfRoot: 0.6 })
        )
        expect(onFocusChange).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'root/a' }))

        // Zoomed to `a`, its child `a1` now spans half the width instead of 30%.
        onNodeClick.mockClear()
        fireEvent.click(chart.element, { clientX: 390, clientY: rowY(2) })
        expect(onNodeClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'root/a/a1' }))
        expect(chart.flameBreadcrumb()).toEqual(['All', 'root', 'a', 'a1'])

        fireEvent.keyDown(chart.element.closest('[tabindex="0"]')!, { key: 'Escape' })
        expect(chart.flameBreadcrumb()).toEqual(['All', 'root', 'a'])

        fireEvent.click(getByText('Reset zoom'))
        expect(chart.flameBreadcrumb()).toEqual(['All'])
        expect(onFocusChange).toHaveBeenLastCalledWith(null)
    })

    it('zooms into a "+N more" bundle of small siblings without reporting a node click', () => {
        const onNodeClick = jest.fn()
        const { chart } = renderFlame({
            onNodeClick,
            data: {
                name: 'p',
                value: 1000,
                children: [
                    { name: 'big', value: 900 },
                    { name: 's1', value: 2 },
                    { name: 's2', value: 2 },
                    { name: 's3', value: 2 },
                ],
            },
        })
        fireEvent.click(chart.element, { clientX: 722, clientY: rowY(1) })
        expect(chart.flameBreadcrumb()).toEqual(['All', 'p', '+3 more'])
        expect(onNodeClick).not.toHaveBeenCalled()
    })

    it('drops a hover from before a data update instead of reading the new tree with old indices', () => {
        const onError = jest.fn()
        const { chart, rerender } = renderFlame({ onError })
        fireEvent.mouseMove(chart.element, { clientX: 600, clientY: rowY(1) })
        rerender(<FlameGraph data={{ name: 'only', value: 1 }} theme={THEME} onError={onError} />)
        expect(onError).not.toHaveBeenCalled()
        expect(chart.canvas.getAttribute('aria-label')).toBe('Flame graph with 1 nodes')
    })

    it('opens on defaultFocusedId and summarizes search matches', () => {
        const { chart } = renderFlame({ defaultFocusedId: 'root/a', search: 'A' })
        expect(chart.flameBreadcrumb()).toEqual(['All', 'root', 'a'])
        expect(chart.flameSearchSummary()).toBe('2 matches · 60% of total')
    })
})
