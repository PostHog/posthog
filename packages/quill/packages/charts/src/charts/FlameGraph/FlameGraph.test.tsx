import { fireEvent } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { mockRect, renderChart, waitForChartTooltip } from '../../testing'
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

function renderFlame(props: Partial<FlameGraphProps> = {}): ReturnType<typeof renderChart> {
    return renderChart(<FlameGraph data={TREE} theme={THEME} {...props} />)
}

describe('FlameGraph', () => {
    afterEach(() => {
        jest.restoreAllMocks()
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
            label: 'the formatted value',
            data: TREE,
            point: [200, rowY(1)],
            config: { valueFormatter: (v) => `${v} ms` },
            expected: ['a', 'Value60 ms', 'Click to zoom in'],
            absent: ['Baseline'],
        },
        {
            label: 'the change against the baseline',
            data: { ...TREE, value: 130, baselineValue: 100, count: 40, baselineCount: 50 },
            point: [400, rowY(0)],
            expected: ['root', 'Value130', 'Baseline100'],
            absent: [],
        },
    ])('shows $label in the tooltip of the hovered node', async ({ data, point, expected, config, absent }) => {
        const { chart } = renderFlame({ data, config })
        fireEvent.mouseMove(chart.element, { clientX: point[0], clientY: point[1] })
        const tooltip = await waitForChartTooltip()
        for (const text of expected) {
            expect(tooltip.textContent).toContain(text)
        }
        for (const text of absent) {
            expect(tooltip.textContent).not.toContain(text)
        }
    })

    it('zooms into a clicked node and zooms back out with Escape and reset', () => {
        const onFocusChange = jest.fn()
        const { chart } = renderFlame({ onFocusChange })
        expect(chart.flame.breadcrumb()).toEqual(['All'])

        fireEvent.click(chart.element, { clientX: 200, clientY: rowY(1) })
        expect(chart.flame.breadcrumb()).toEqual(['All', 'root', 'a'])
        expect(onFocusChange).toHaveBeenLastCalledWith(
            expect.objectContaining({ kind: 'node', node: expect.objectContaining({ name: 'a', depth: 1 }) })
        )

        // Zoomed to `a`, its child `a1` now spans half the width instead of 30%.
        fireEvent.click(chart.element, { clientX: 390, clientY: rowY(2) })
        expect(chart.flame.breadcrumb()).toEqual(['All', 'root', 'a', 'a1'])

        fireEvent.keyDown(chart.flame.viewport(), { key: 'Escape' })
        expect(chart.flame.breadcrumb()).toEqual(['All', 'root', 'a'])

        fireEvent.click(chart.flame.resetButton()!)
        expect(chart.flame.breadcrumb()).toEqual(['All'])
        expect(onFocusChange).toHaveBeenLastCalledWith(null)
        expect(onFocusChange).toHaveBeenCalledTimes(4)
    })

    it('zooms into a "+N more" bundle of small siblings', () => {
        const { chart } = renderFlame({
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
        expect(chart.flame.breadcrumb()).toEqual(['All', 'p', '+3 more'])
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
        const tooltip = await waitForChartTooltip()
        expect(tooltip.textContent).toContain('2 smaller roots')
        expect(onError).not.toHaveBeenCalled()
    })

    it('repaints at the new size when its container resizes', () => {
        const { chart } = renderFlame()
        expect(chart.canvas.style.width).toBe('800px')
        jest.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ ...mockRect, width: 400, right: 400 })
        // A restored context makes the canvas re-measure, the same path a resize takes.
        fireEvent(chart.canvas, new Event('contextrestored'))
        expect(chart.canvas.style.width).toBe('400px')
    })

    it('lists group colors through the shared legend accessor, largest self share first', () => {
        const data: FlameNode = {
            name: 'main',
            value: 100,
            group: 'app',
            children: [
                { name: 'query', value: 70, group: 'db' },
                { name: 'render', value: 10, group: 'app' },
            ],
        }
        const { chart } = renderFlame({ data })
        expect(chart.legendItems()).toEqual([
            { label: 'db', secondaryLabel: '70%' },
            { label: 'app', secondaryLabel: '30%' },
        ])
    })

    it('measures legend shares on the laid-out widths, so concurrent children cannot pass 100%', () => {
        const data: FlameNode = {
            name: 'main',
            value: 100,
            group: 'app',
            children: [
                { name: 'query', value: 100, group: 'db' },
                { name: 'render', value: 100, group: 'app' },
            ],
        }
        const { chart } = renderFlame({ data })
        expect(chart.legendItems()).toEqual([
            { label: 'app', secondaryLabel: '50%' },
            { label: 'db', secondaryLabel: '50%' },
        ])
    })

    it('opens on defaultFocusedId only on mount and summarizes search matches', () => {
        const { chart, rerender } = renderFlame({ defaultFocusedId: 'root/a', search: 'A' })
        expect(chart.flame.breadcrumb()).toEqual(['All', 'root', 'a'])
        expect(chart.flame.searchSummary()).toBe('2 matches · 60% of total')

        rerender(<FlameGraph data={TREE} theme={THEME} defaultFocusedId="root/b" search="A" />)
        expect(chart.flame.breadcrumb()).toEqual(['All', 'root', 'a'])
    })
})
