import { DataModelingEdge } from '~/types'

import { HIDDEN_DOWNSTREAM_COUNT_CAP, bridgeHiddenNodes } from './lineageHiddenNodes'

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
            name: 'keeps hidden hubs as nodes instead of multiplying edges through them',
            edges: [
                edge('a1', 'h1'),
                edge('a2', 'h1'),
                edge('a3', 'h1'),
                edge('h1', 'h2'),
                edge('h2', 'b1'),
                edge('h2', 'b2'),
                edge('h2', 'b3'),
            ],
            scope: ['a1', 'a2', 'a3', 'h1', 'h2', 'b1', 'b2', 'b3'],
            visible: ['a1', 'a2', 'a3', 'b1', 'b2', 'b3'],
            expectedEdges: ['a1>h1', 'a2>h1', 'a3>h1', 'h1>h2', 'h2>b1', 'h2>b2', 'h2>b3'],
            expectedCounts: {},
            expectedHubs: ['h1', 'h2'],
        },
        {
            name: 'caps the hidden count past the display limit',
            edges: Array.from({ length: HIDDEN_DOWNSTREAM_COUNT_CAP + 5 }, (_, index) => edge('v', `m${index}`)),
            scope: ['v', ...Array.from({ length: HIDDEN_DOWNSTREAM_COUNT_CAP + 5 }, (_, index) => `m${index}`)],
            visible: ['v'],
            expectedEdges: [],
            expectedCounts: { v: HIDDEN_DOWNSTREAM_COUNT_CAP + 1 },
        },
        {
            name: 'does not walk through a node outside the scope',
            edges: [edge('a', 'out'), edge('out', 'b')],
            scope: ['a', 'b'],
            visible: ['a', 'b'],
            expectedEdges: [],
            expectedCounts: {},
        },
    ])('$name', ({ edges, scope, visible, expectedEdges, expectedCounts, expectedHubs = [] }) => {
        const bridging = bridgeHiddenNodes(edges, new Set(scope), new Set(visible))

        const renderedEdges = bridging.edges.map(
            (e) => `${e.source_id}>${e.target_id}${e.throughHiddenNodes ? ' hidden' : ''}`
        )
        expect(renderedEdges.sort()).toEqual(expectedEdges)
        expect(Object.fromEntries(bridging.hiddenDownstreamCounts)).toEqual(expectedCounts)
        expect([...bridging.hubNodeIds].sort()).toEqual(expectedHubs)
    })
})
