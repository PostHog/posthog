import { computeSankeyLayout, sankeyHitAt } from './sankey-data'
import type { ComputeSankeyLayoutOptions, SankeyLinkInput, SankeyNodeInput } from './sankey-data'

const PLOT = { plotLeft: 0, plotTop: 0, plotWidth: 600, plotHeight: 300 }

const NODES: SankeyNodeInput[] = [
    { id: 'start' },
    { id: 'a', label: 'Tool A' },
    { id: 'b', label: 'Tool B' },
    { id: 'done', label: 'Completed' },
]
const LINKS: SankeyLinkInput[] = [
    { source: 'start', target: 'a', value: 30 },
    { source: 'start', target: 'b', value: 10 },
    { source: 'a', target: 'done', value: 30 },
    { source: 'b', target: 'done', value: 10 },
]

function layoutOf(
    overrides: Partial<ComputeSankeyLayoutOptions<unknown>> = {}
): ReturnType<typeof computeSankeyLayout> {
    return computeSankeyLayout({
        nodes: NODES,
        links: LINKS,
        plot: PLOT,
        nodeWidth: 10,
        nodePadding: 8,
        nodeAlign: 'justify',
        preserveNodeOrder: false,
        colorForLabel: () => '#111111',
        resolveColor: (c) => c,
        ...overrides,
    })
}

describe('computeSankeyLayout', () => {
    it('places nodes in columns by depth and sums flow into node values', () => {
        const layout = layoutOf()
        const byId = Object.fromEntries(layout.nodes.map((n) => [n.id, n]))
        expect(byId.start.column).toBe(0)
        expect(byId.a.column).toBe(1)
        expect(byId.b.column).toBe(1)
        expect(byId.done.column).toBe(2)
        expect(layout.columnCount).toBe(3)
        expect(byId.start.value).toBe(40)
        expect(byId.done.value).toBe(40)
        // The total is the inflow of the source nodes, which is what shares are measured against.
        expect(layout.total).toBe(40)
    })

    it('keeps a flow that ends early in its own column under left alignment', () => {
        const links: SankeyLinkInput[] = [...LINKS, { source: 'start', target: 'ended', value: 5 }]
        const nodes: SankeyNodeInput[] = [...NODES, { id: 'ended', label: 'Ended' }]
        const justified = layoutOf({ nodes, links })
        const left = layoutOf({ nodes, links, nodeAlign: 'left' })
        expect(justified.nodes.find((n) => n.id === 'ended')?.column).toBe(2)
        expect(left.nodes.find((n) => n.id === 'ended')?.column).toBe(1)
    })

    it('resolves node colors by label and defaults link color to the source node', () => {
        const layout = layoutOf({
            nodes: [...NODES.slice(0, 3), { id: 'done', label: 'Completed', color: 'var(--success)' }],
            colorForLabel: (label) => (label === 'Tool A' ? '#aaaaaa' : '#bbbbbb'),
            resolveColor: (c) => (c.startsWith('var(') ? '#00ff00' : c),
        })
        const byId = Object.fromEntries(layout.nodes.map((n) => [n.id, n]))
        expect(byId.a.color).toBe('#aaaaaa')
        expect(byId.done.color).toBe('#00ff00')
        const aToDone = layout.links.find((l) => l.source.id === 'a' && l.target.id === 'done')
        expect(aToDone?.color).toBe('#aaaaaa')
    })

    it('returns an empty layout without links and throws on a link to a missing node', () => {
        expect(layoutOf({ links: [] }).nodes).toHaveLength(0)
        expect(() => layoutOf({ links: [{ source: 'start', target: 'nope', value: 1 }] })).toThrow('missing: nope')
    })
})

describe('sankeyHitAt', () => {
    const layout = layoutOf()
    const node = (id: string): NonNullable<(typeof layout.nodes)[number]> => layout.nodes.find((n) => n.id === id)!

    it('resolves a node box, a ribbon between columns, and empty space', () => {
        const start = node('start')
        const nodeHit = sankeyHitAt(layout, { x: (start.x0 + start.x1) / 2, y: (start.y0 + start.y1) / 2 })
        expect(nodeHit).toEqual({ kind: 'node', index: layout.nodes.indexOf(start) })

        const aToDone = layout.links.findIndex((l) => l.source.id === 'a' && l.target.id === 'done')
        const link = layout.links[aToDone]
        // Mid-ribbon, the curve passes through the average of its end y values.
        const linkHit = sankeyHitAt(layout, {
            x: (link.source.x1 + link.target.x0) / 2,
            y: (link.y0 + link.y1) / 2,
        })
        expect(linkHit).toEqual({ kind: 'link', index: aToDone })

        expect(sankeyHitAt(layout, { x: -50, y: -50 })).toBeNull()
    })
})
