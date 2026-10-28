import { LINEAGE_MIN_ZOOM, lineageFitTarget } from './lineageFit'

const node = (id: string, x: number, y: number): { id: string; position: { x: number; y: number } } => ({
    id,
    position: { x, y },
})

describe('lineageFitTarget', () => {
    const viewport = { width: 1000, height: 800 }

    test.each([
        {
            name: 'fits every node when they fit above the zoom floor',
            nodes: [node('a', 0, 0), node('b', 400, 0), node('c', 400, 300)],
            bounds: { x: 0, y: 0, width: 600, height: 400 },
            expected: { ids: ['a', 'b', 'c'], maxZoom: undefined },
        },
        {
            name: 'centers on the node nearest the centroid when the graph needs a zoom below the floor',
            nodes: [node('a', 0, 0), node('b', 200, 0), node('c', 0, 200), node('d', 200, 200), node('far', 0, 100000)],
            bounds: { x: 0, y: 0, width: 400, height: 100200 },
            expected: { ids: ['c'], maxZoom: LINEAGE_MIN_ZOOM },
        },
    ])('$name', ({ nodes, bounds, expected }) => {
        const target = lineageFitTarget(nodes, bounds, viewport, 0.2)

        expect({ ids: target.nodes.map((n) => n.id), maxZoom: target.maxZoom }).toEqual(expected)
    })
})
