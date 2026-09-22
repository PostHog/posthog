import { fireEvent, waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { getHogChartTooltip, renderHogChart } from '../../testing'
import { computeSankeyLayout } from './sankey-data'
import type { SankeyLinkInput, SankeyNodeInput } from './sankey-data'
import { SankeyChart } from './SankeyChart'

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

    it('shows the hovered node in the tooltip, reports it once, and fires onNodeClick for it', async () => {
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
    })

    it('shows the tooltip on a first tap and fires onNodeClick on the second', async () => {
        const onNodeClick = jest.fn()
        const { chart } = renderHogChart(
            <SankeyChart nodes={NODES} links={LINKS} theme={THEME} onNodeClick={onNodeClick} />,
            { nativeTooltip: true }
        )
        // A tap sends no mousemove first, so nothing is hovered when the click arrives. jsdom has
        // no PointerEvent, so the pointer type rides on a MouseEvent React reads it from.
        const tap = (): void => {
            const down = Object.assign(new MouseEvent('pointerdown', { bubbles: true }), { pointerType: 'touch' })
            fireEvent(chart.element, down)
            fireEvent.click(chart.element, nodeCenter('a'))
        }
        tap()
        await waitFor(() => expect(getHogChartTooltip()?.textContent).toContain('Tool A'))
        expect(onNodeClick).not.toHaveBeenCalled()
        tap()
        expect(onNodeClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }))
    })
})
