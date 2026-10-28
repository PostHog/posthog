import { DataModelingEdge } from '~/types'

import { bridgeHiddenNodes } from './lineageHiddenNodes'

const edge = (source_id: string, target_id: string): DataModelingEdge => ({
    id: `${source_id}>${target_id}`,
    source_id,
    target_id,
})

describe('bridgeHiddenNodes', () => {
    test.each([
        {
            name: 'connects across one hidden node',
            edges: [edge('a', 'h'), edge('h', 'b')],
            scope: ['a', 'h', 'b'],
            visible: ['a', 'b'],
            expectedEdges: ['a>b hidden'],
            expectedCounts: {},
        },
        {
            name: 'connects across a chain of hidden nodes',
            edges: [edge('a', 'h1'), edge('h1', 'h2'), edge('h2', 'b')],
            scope: ['a', 'h1', 'h2', 'b'],
            visible: ['a', 'b'],
            expectedEdges: ['a>b hidden'],
            expectedCounts: {},
        },
        {
            name: 'keeps the real edge when a hidden path runs alongside it',
            edges: [edge('a', 'b'), edge('a', 'h'), edge('h', 'b')],
            scope: ['a', 'h', 'b'],
            visible: ['a', 'b'],
            expectedEdges: ['a>b'],
            expectedCounts: {},
        },
        {
            name: 'fans out from a hidden node to every visible child',
            edges: [edge('a', 'h'), edge('h', 'b'), edge('h', 'c')],
            scope: ['a', 'h', 'b', 'c'],
            visible: ['a', 'b', 'c'],
            expectedEdges: ['a>b hidden', 'a>c hidden'],
            expectedCounts: {},
        },
        {
            name: 'counts hidden nodes that lead to no visible node',
            edges: [edge('v', 'm1'), edge('v', 'h'), edge('h', 'm2')],
            scope: ['v', 'm1', 'h', 'm2'],
            visible: ['v'],
            expectedEdges: [],
            expectedCounts: { v: 3 },
        },
        {
            name: 'does not walk through a node outside the scope',
            edges: [edge('a', 'out'), edge('out', 'b')],
            scope: ['a', 'b'],
            visible: ['a', 'b'],
            expectedEdges: [],
            expectedCounts: {},
        },
    ])('$name', ({ edges, scope, visible, expectedEdges, expectedCounts }) => {
        const bridging = bridgeHiddenNodes(edges, new Set(scope), new Set(visible))

        const renderedEdges = bridging.edges.map(
            (e) => `${e.source_id}>${e.target_id}${e.throughHiddenNodes ? ' hidden' : ''}`
        )
        expect(renderedEdges.sort()).toEqual(expectedEdges)
        expect(Object.fromEntries(bridging.hiddenDownstreamCounts)).toEqual(expectedCounts)
    })
})
