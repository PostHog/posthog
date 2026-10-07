import { fireEvent, render, waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { getHogChartTooltip, renderHogChart } from '../../testing'
import { computeSankeyLayout } from './sankey-data'
import type { SankeyLinkInput, SankeyNodeDatum, SankeyNodeInput } from './sankey-data'
import { labelsSharingLastGap, outsideLabelWidth, sankeyLabelBoxes } from './sankey-labels'
import { SankeyChart } from './SankeyChart'
import { fitHeader } from './SankeyColumnLabels'

const THEME: ChartTheme = { colors: ['#1f77b4', '#ff7f0e', '#2ca02c'], backgroundColor: '#ffffff' }

const NODES: SankeyNodeInput[] = [
    { id: 'start', label: 'Start' },
    { id: 'a', label: 'Tool A' },
    { id: 'done', label: 'Completed' },
]
const LINKS: SankeyLinkInput[] = [
    { source: 'start', target: 'a', value: 12 },
    { source: 'a', target: 'done', value: 12 },
]

// Mirrors the chart's own layout at the mocked 800x400 wrapper, so a cursor lands on a known node.
function nodeCenter(id: string): { clientX: number; clientY: number } {
    const layout = computeSankeyLayout({
        nodes: NODES,
        links: LINKS,
        plot: { plotLeft: 8, plotTop: 8, plotWidth: 800 - 16, plotHeight: 400 - 16 },
        nodeWidth: 12,
        nodePadding: 8,
        nodeAlign: 'justify',
        preserveNodeOrder: false,
        colorForLabel: () => '#000',
        resolveColor: (c) => c,
    })
    const node = layout.nodes.find((n) => n.id === id)!
    return { clientX: (node.x0 + node.x1) / 2, clientY: (node.y0 + node.y1) / 2 }
}

describe('SankeyChart', () => {
    it('renders node labels and column headers as DOM overlays', () => {
        const { chart } = renderHogChart(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                config={{ columnLabels: ['Init', '1st tool', 'Outcome', 'unused'], showNodeValues: true }}
            />
        )
        expect(chart.sankeyNodeLabels()).toEqual(['Start 12', 'Tool A 12', 'Completed 12'])
        expect(chart.sankeyColumnLabels()).toEqual(['Init', '1st tool', 'Outcome'])
        expect(chart.canvas.getAttribute('aria-label')).toBe('Sankey chart with 3 nodes and 2 links')
    })

    it('drops the label of a thin node that would print over its larger neighbor', () => {
        // Two thin nodes stacked in one column: their boxes are a pixel or two tall, so their label
        // centers sit closer than a line of text. The larger flow keeps its label.
        const { chart } = renderHogChart(
            <SankeyChart
                nodes={[
                    { id: 'start', label: 'Start' },
                    { id: 'a', label: 'Big' },
                    { id: 'b', label: 'Thin' },
                    { id: 'c', label: 'Thinner' },
                ]}
                links={[
                    { source: 'start', target: 'a', value: 400 },
                    { source: 'start', target: 'b', value: 2 },
                    { source: 'start', target: 'c', value: 1 },
                ]}
                theme={THEME}
                config={{ nodePadding: 0 }}
            />
        )
        expect(chart.sankeyNodeLabels()).toEqual(['Start', 'Big', 'Thin'])
    })

    it('shows the hovered node in the tooltip, reports it once, and fires onNodeClick for it', async () => {
        const onNodeClick = jest.fn()
        const onHoverChange = jest.fn()
        const { chart, rerender } = renderHogChart(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                onNodeClick={onNodeClick}
                onHoverChange={onHoverChange}
            />,
            { nativeTooltip: true }
        )
        await waitFor(() => {
            fireEvent.mouseMove(chart.element, nodeCenter('a'))
            expect(getHogChartTooltip()?.textContent).toContain('Tool A')
        })
        // The share is of the total inflow, so the only path reads as 100%.
        expect(getHogChartTooltip()?.textContent).toContain('100%')
        fireEvent.click(chart.element)
        expect(onNodeClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'a', value: 12 }))

        // Repeated moves inside one node report a single hover; leaving reports null.
        fireEvent.mouseMove(chart.element, nodeCenter('a'))
        expect(onHoverChange.mock.calls).toEqual([[{ kind: 'node', node: expect.objectContaining({ id: 'a' }) }]])
        fireEvent.mouseLeave(chart.element)
        expect(onHoverChange).toHaveBeenLastCalledWith(null)

        await waitFor(() => {
            fireEvent.mouseMove(chart.element, nodeCenter('a'))
            expect(getHogChartTooltip()?.textContent).toContain('Tool A')
        })
        onNodeClick.mockClear()
        rerender(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                onNodeClick={onNodeClick}
                onHoverChange={onHoverChange}
                config={{ nodeWidth: 24 }}
            />
        )
        await waitFor(() => expect(getHogChartTooltip()).toBeNull())
        // The hovered node belonged to the old layout, so the host is told it is gone.
        expect(onHoverChange).toHaveBeenLastCalledWith(null)
        fireEvent.click(chart.element)
        expect(onNodeClick).not.toHaveBeenCalled()
    })

    it('shows the tooltip on a first tap, fires onNodeClick on the second, and clears on an empty tap', async () => {
        const onNodeClick = jest.fn()
        const onHoverChange = jest.fn()
        const { chart } = renderHogChart(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                onNodeClick={onNodeClick}
                onHoverChange={onHoverChange}
            />,
            { nativeTooltip: true }
        )
        // A tap sends no mousemove first, so nothing is hovered when the click arrives. jsdom has
        // no PointerEvent, so the pointer type rides on a MouseEvent React reads it from.
        const tap = (at: { clientX: number; clientY: number }): void => {
            const down = Object.assign(new MouseEvent('pointerdown', { bubbles: true }), { pointerType: 'touch' })
            fireEvent(chart.element, down)
            fireEvent.click(chart.element, at)
        }
        tap(nodeCenter('a'))
        await waitFor(() => expect(getHogChartTooltip()?.textContent).toContain('Tool A'))
        expect(onNodeClick).not.toHaveBeenCalled()
        tap(nodeCenter('a'))
        expect(onNodeClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }))

        // Inside the margin, outside every node and ribbon.
        tap({ clientX: 2, clientY: 2 })
        expect(onHoverChange).toHaveBeenLastCalledWith(null)
    })

    it('ignores a tap on an interactive overlay over a node', () => {
        const onNodeClick = jest.fn()
        const onHoverChange = jest.fn()
        const { chart, getByRole } = renderHogChart(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                onNodeClick={onNodeClick}
                onHoverChange={onHoverChange}
                config={{ tooltip: { enabled: false } }}
            >
                <button data-hog-charts-interactive-overlay="">card</button>
            </SankeyChart>
        )
        const down = Object.assign(new MouseEvent('pointerdown', { bubbles: true }), { pointerType: 'touch' })
        fireEvent(chart.element, down)
        fireEvent.click(getByRole('button'), nodeCenter('a'))

        expect(onNodeClick).not.toHaveBeenCalled()
        expect(onHoverChange).not.toHaveBeenCalledWith(expect.objectContaining({ kind: 'node' }))
    })

    it('fires the click on the first tap when the tooltip is disabled', () => {
        const onNodeClick = jest.fn()
        const { chart } = renderHogChart(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                onNodeClick={onNodeClick}
                config={{ tooltip: { enabled: false } }}
            />
        )
        const down = Object.assign(new MouseEvent('pointerdown', { bubbles: true }), { pointerType: 'touch' })
        fireEvent(chart.element, down)
        fireEvent.click(chart.element, nodeCenter('a'))

        expect(onNodeClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }))
    })

    it('ignores hover and clicks from an interactive overlay child', async () => {
        const onNodeClick = jest.fn()
        const { chart } = renderHogChart(
            <SankeyChart nodes={NODES} links={LINKS} theme={THEME} onNodeClick={onNodeClick}>
                <button data-hog-charts-interactive-overlay>overlay</button>
            </SankeyChart>,
            { nativeTooltip: true }
        )
        await waitFor(() => {
            fireEvent.mouseMove(chart.element, nodeCenter('a'))
            expect(getHogChartTooltip()?.textContent).toContain('Tool A')
        })
        const overlay = chart.element.querySelector('[data-hog-charts-interactive-overlay]')!
        fireEvent.mouseMove(overlay, nodeCenter('a'))
        await waitFor(() => expect(getHogChartTooltip()).toBeNull())
        fireEvent.click(overlay, nodeCenter('a'))
        expect(onNodeClick).not.toHaveBeenCalled()
    })

    it.each([
        {
            name: 'a link endpoint',
            broken: { links: [LINKS[0], { source: 'a', target: 'missing', value: 12 }] },
        },
        { name: 'the node padding', broken: { config: { nodePadding: -1 } } },
        { name: 'a NaN pin', broken: { nodes: [{ ...NODES[0], column: NaN }, ...NODES.slice(1)] } },
    ])('recovers from an invalid graph when only $name is corrected', ({ broken }) => {
        jest.spyOn(console, 'error').mockImplementation(() => {})
        const onError = jest.fn()
        const { container, rerender } = render(
            <SankeyChart nodes={NODES} links={LINKS} theme={THEME} onError={onError} {...broken} />
        )
        expect(onError).toHaveBeenCalled()
        expect(container.textContent).toContain('Something went wrong')

        rerender(<SankeyChart nodes={NODES} links={LINKS} theme={THEME} onError={onError} />)
        expect(container.textContent).not.toContain('Something went wrong')
    })

    it('finds labels that face each other across the gap the last two columns share', () => {
        const node = (id: string, column: number, y0: number): SankeyNodeDatum => ({
            id,
            label: id,
            color: '#000',
            index: 0,
            column,
            value: 1,
            x0: 0,
            x1: 0,
            y0,
            y1: y0 + 4,
        })
        const first = node('first', 0, 100)
        const penultimate = node('penultimate', 1, 100)
        const last = node('last', 2, 102)
        const lastFarAway = node('lastFarAway', 2, 200)
        expect(labelsSharingLastGap(new Set([first, penultimate, last, lastFarAway]), 3)).toEqual(
            new Set([penultimate, last])
        )
    })

    it('shows the node tooltip when the pointer is over its label, not the ribbon under it', async () => {
        const { chart } = renderHogChart(<SankeyChart nodes={NODES} links={LINKS} theme={THEME} />, {
            nativeTooltip: true,
        })
        // Right of the Start node, inside its label and over the Start -> Tool A ribbon.
        const start = nodeCenter('start')
        await waitFor(() => {
            fireEvent.mouseMove(chart.element, { clientX: start.clientX + 17, clientY: start.clientY })
            expect(getHogChartTooltip()?.textContent).toContain('Start')
        })
        expect(getHogChartTooltip()?.textContent).not.toContain('→')
    })

    it('places last-column labels outside the nodes when asked, and truncates headers to their span', () => {
        const layout = computeSankeyLayout({
            nodes: NODES,
            links: LINKS,
            plot: { plotLeft: 8, plotTop: 8, plotWidth: 600, plotHeight: 300 },
            nodeWidth: 12,
            nodePadding: 8,
            nodeAlign: 'justify',
            preserveNodeOrder: false,
            colorForLabel: () => '#000',
            resolveColor: (c) => c,
        })
        const options = { showValues: false, valueFormatter: String, outsideWidth: 120 }
        const sideOfLast = (lastColumnLabels: 'inside' | 'outside'): string | undefined =>
            sankeyLabelBoxes(layout, { ...options, lastColumnLabels }).find((box) => box.text === 'Completed')?.side
        expect([sideOfLast('inside'), sideOfLast('outside')]).toEqual(['left', 'right'])

        expect(fitHeader('Outcome', 1000)).toBe('Outcome')
        expect(fitHeader('4th tool', 8)).toBe('4th…')
    })

    it('draws no label where a narrow chart leaves it no room', () => {
        const layout = computeSankeyLayout({
            nodes: NODES,
            links: LINKS,
            plot: { plotLeft: 8, plotTop: 8, plotWidth: 40, plotHeight: 300 },
            nodeWidth: 12,
            nodePadding: 8,
            nodeAlign: 'justify',
            preserveNodeOrder: false,
            colorForLabel: () => '#000',
            resolveColor: (c) => c,
        })
        const boxes = sankeyLabelBoxes(layout, {
            showValues: false,
            valueFormatter: String,
            lastColumnLabels: 'inside',
            outsideWidth: 0,
        })
        expect(boxes).toEqual([])
    })

    it.each([
        { nodeAlign: 'left' as const, sizedBy: 'Completed' },
        { nodeAlign: 'justify' as const, sizedBy: 'Left after the first tool' },
    ])('sizes the outside margin by the sinks in the last column under $nodeAlign', ({ nodeAlign, sizedBy }) => {
        const nodes: SankeyNodeInput[] = [...NODES, { id: 'early', label: 'Left after the first tool' }]
        const links: SankeyLinkInput[] = [...LINKS, { source: 'start', target: 'early', value: 3 }]
        const onlySink = outsideLabelWidth([{ id: 'only', label: sizedBy }], [], nodeAlign, false, String)
        expect(outsideLabelWidth(nodes, links, nodeAlign, false, String)).toBe(onlySink)
    })

    it('keeps room for column headers when a consumer overrides the top margin', () => {
        const { chart } = renderHogChart(
            <SankeyChart
                nodes={NODES}
                links={LINKS}
                theme={THEME}
                config={{ columnLabels: ['Init', 'Tool', 'Outcome'], margins: { top: 0 } }}
            />
        )
        // Start fills the plot height, so its label sits at the plot's vertical center: 18px of
        // header room above a 400px wrapper with an 8px bottom margin.
        const start = Array.from(
            chart.element.querySelectorAll<HTMLElement>('[data-attr="hog-chart-sankey-node-label"]')
        ).find((label) => label.textContent?.startsWith('Start'))
        expect(start?.style.top).toBe(`${18 + (400 - 18 - 8) / 2}px`)
    })
})
