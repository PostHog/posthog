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
        // `SankeyHighlight.linkIndices` and click handlers address links by input position.
        expect(layout.links.map((l) => [l.source.id, l.target.id])).toEqual(LINKS.map((l) => [l.source, l.target]))
    })

    it('places a flow that ends early by alignment: justify, left, and right', () => {
        const links: SankeyLinkInput[] = [...LINKS, { source: 'start', target: 'ended', value: 5 }]
        const nodes: SankeyNodeInput[] = [...NODES, { id: 'ended', label: 'Ended' }]
        const columnOf = (align: 'justify' | 'left' | 'right', id: string): number | undefined =>
            layoutOf({ nodes, links, nodeAlign: align }).nodes.find((n) => n.id === id)?.column
        expect(columnOf('justify', 'ended')).toBe(2)
        expect(columnOf('left', 'ended')).toBe(1)
        // Right alignment counts from the sink, so the source stays first and the early end moves last.
        expect([columnOf('right', 'start'), columnOf('right', 'a'), columnOf('right', 'ended')]).toEqual([0, 1, 2])
    })

    it('pins a node to its own column and widens the graph to fit it', () => {
        // A late stage with no link from the earlier stages: depth alone would put `late` in the
        // first column, and the graph would have three columns instead of five.
        const nodes: SankeyNodeInput[] = [...NODES, { id: 'late', column: 3 }, { id: 'last', column: 4 }]
        const links: SankeyLinkInput[] = [...LINKS, { source: 'late', target: 'last', value: 2 }]
        const layout = layoutOf({ nodes, links, nodeAlign: 'left' })
        const columnOf = (id: string): number | undefined => layout.nodes.find((n) => n.id === id)?.column
        expect([columnOf('start'), columnOf('done'), columnOf('late'), columnOf('last')]).toEqual([0, 2, 3, 4])
        expect(layout.columnCount).toBe(5)
    })

    it('lays out a pinned graph with an empty column between the pins', () => {
        // Only two nodes, pinned three columns apart with nothing to naturally fill the columns
        // between them: the graph must not crash spacing out a column with zero nodes in it.
        const nodes: SankeyNodeInput[] = [
            { id: 'x', column: 0 },
            { id: 'y', column: 3 },
        ]
        const links: SankeyLinkInput[] = [{ source: 'x', target: 'y', value: 5 }]
        expect(() => layoutOf({ nodes, links, nodeAlign: 'left' })).not.toThrow()
        const layout = layoutOf({ nodes, links, nodeAlign: 'left' })
        const columnOf = (id: string): number | undefined => layout.nodes.find((n) => n.id === id)?.column
        expect([columnOf('x'), columnOf('y')]).toEqual([0, 3])
        expect(layout.columnCount).toBe(4)
        // Headers over the empty columns need an x too, evenly spaced between the pinned ones.
        expect(layout.columnX).toEqual([0, 590 / 3, (2 * 590) / 3, 590])
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

    it('returns an empty layout when all link values are zero', () => {
        const layout = layoutOf({ links: [{ source: 'start', target: 'a', value: 0 }] })
        expect(layout.nodes).toHaveLength(0)
        expect(layout.total).toBe(0)
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

    it('hits a zero-value node across the 1px the draw code floors it to', () => {
        const withOrphan = layoutOf({ nodes: [...NODES, { id: 'orphan' }], links: LINKS })
        const orphan = withOrphan.nodes.find((n) => n.id === 'orphan')!
        expect(orphan.y1 - orphan.y0).toBe(0)

        // Probe inside the floored band but outside the raw box, so dropping the floor fails here.
        const hit = sankeyHitAt(withOrphan, { x: (orphan.x0 + orphan.x1) / 2, y: orphan.y0 + 0.5 })
        expect(hit).toEqual({ kind: 'node', index: withOrphan.nodes.indexOf(orphan) })
    })
})
