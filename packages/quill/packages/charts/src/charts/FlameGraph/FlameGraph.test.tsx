import { fireEvent } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { mockRect, renderHogChart, waitForHogChartTooltip } from '../../testing'
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

    it.each<{
        label: string
        data: FlameNode
        point: [number, number]
        expected: string[]
        config?: FlameGraphProps['config']
        absent: string[]
    }>([
        {
            label: 'total, self and shares',
            data: TREE,
            point: [200, rowY(1)],
            expected: ['a', 'Total60 (60%)', 'Self30', 'Of parent60%', 'Click to zoom in'],
            absent: ['Of total'],
        },
        {
            label: 'the change against the baseline',
            data: { ...TREE, value: 130, baselineValue: 100, count: 40, baselineCount: 50 },
            point: [400, rowY(0)],
            expected: ['root', 'Count40', 'Baseline100', 'Change+30%'],
            absent: [],
        },
        {
            label: 'value and shares without a self row, siblings widest first, under the breakdown preset',
            data: {
                name: 'all',
                value: 100,
                children: [
                    { name: 'small', value: 30 },
                    { name: 'wide', value: 60 },
                ],
            },
            point: [200, rowY(1)],
            config: { preset: 'breakdown', valueFormatter: (v) => `${v} views` },
            expected: ['wide', 'Value60 views', 'Of parent60%', 'Of total60%'],
            absent: ['Self', 'Total60'],
        },
    ])('shows $label in the tooltip of the hovered node', async ({ data, point, expected, config, absent }) => {
        const { chart } = renderFlame({ data, config })
        fireEvent.mouseMove(chart.element, { clientX: point[0], clientY: point[1] })
        const tooltip = await waitForHogChartTooltip()
        for (const text of expected) {
            expect(tooltip.textContent).toContain(text)
        }
        for (const text of absent) {
            expect(tooltip.textContent).not.toContain(text)
        }
    })

    it('zooms into a clicked node, reports it, and zooms back out with Escape and reset', () => {
        const onNodeClick = jest.fn()
        const onFocusChange = jest.fn()
        const { chart, container } = renderFlame({ onNodeClick, onFocusChange })
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

        fireEvent.keyDown(container.querySelector('[data-attr="hog-chart-flame-viewport"]')!, { key: 'Escape' })
        expect(chart.flameBreadcrumb()).toEqual(['All', 'root', 'a'])

        fireEvent.click(container.querySelector('[data-attr="hog-chart-flame-reset"]')!)
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
        expect(chart.canvas.getAttribute('aria-label')).toBe('Flame graph with 1 node')
    })

    it('describes a "+N more" bundle of roots, which have no parent', async () => {
        const onError = jest.fn()
        const { chart } = renderFlame({
            onError,
            data: [
                { name: 'big', value: 1000 },
                { name: 'tiny1', value: 1 },
                { name: 'tiny2', value: 1 },
            ],
        })
        fireEvent.mouseMove(chart.element, { clientX: 799, clientY: rowY(0) })
        const tooltip = await waitForHogChartTooltip()
        expect(tooltip.textContent).toContain('2 smaller roots')
        expect(onError).not.toHaveBeenCalled()
    })

    it('repaints at the new size when its container resizes', () => {
        const { chart } = renderFlame()
        expect(chart.canvas.style.width).toBe('800px')
        const rect = jest.spyOn(Element.prototype, 'getBoundingClientRect')
        try {
            rect.mockReturnValue({ ...mockRect, width: 400, right: 400 })
            // A restored context makes the canvas re-measure, the same path a resize takes.
            fireEvent(chart.canvas, new Event('contextrestored'))
            expect(chart.canvas.style.width).toBe('400px')
        } finally {
            rect.mockReturnValue(mockRect)
        }
    })

    it('lists group colors through the shared legend accessor, largest self share first', () => {
        const { chart } = renderFlame({
            data: {
                name: 'main',
                value: 100,
                group: 'app',
                children: [
                    { name: 'query', value: 70, group: 'db' },
                    { name: 'render', value: 10, group: 'app' },
                ],
            },
        })
        expect(chart.legendItems()).toEqual([
            { label: 'db', secondaryLabel: '70%' },
            { label: 'app', secondaryLabel: '30%' },
        ])
    })

    it('opens on defaultFocusedId and summarizes search matches', () => {
        const { chart } = renderFlame({ defaultFocusedId: 'root/a', search: 'A' })
        expect(chart.flameBreadcrumb()).toEqual(['All', 'root', 'a'])
        expect(chart.flameSearchSummary()).toBe('2 matches · 60% of total')
    })
})
