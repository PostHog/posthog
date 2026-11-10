import { DataModelingEdge, DataModelingNode } from '~/types'

import {
    LineageSearchMode,
    buildAdjacencyMaps,
    edgesWithinNodes,
    matchNodesByName,
    nodeIdsForLineageSearch,
    orderedNodesForLineageSearch,
    parseLineageSearch,
    traverseLineage,
} from './lineageSearch'

const node = (id: string, name: string): DataModelingNode => ({ id, name, type: 'view' }) as DataModelingNode
const edge = (source_id: string, target_id: string): DataModelingEdge =>
    ({ id: `${source_id}-${target_id}`, source_id, target_id }) as DataModelingEdge

// events -> orders -> orders_daily -> revenue_endpoint
const EDGES = [edge('events', 'orders'), edge('orders', 'orders_daily'), edge('orders_daily', 'revenue_endpoint')]

describe('lineageSearch', () => {
    it.each([
        ['orders', 'search', 'orders'],
        ['+orders', 'upstream', 'orders'],
        ['orders+', 'downstream', 'orders'],
        ['+orders+', 'both', 'orders'],
        ['  +orders  ', 'upstream', 'orders'],
        ['+', 'upstream', ''],
    ])('parses %p as %s of %p', (raw, mode, term) => {
        expect(parseLineageSearch(raw)).toEqual({ mode, term })
    })

    it.each([
        ['upstream', 'orders_daily', ['orders_daily', 'orders', 'events']],
        ['downstream', 'orders', ['orders', 'orders_daily', 'revenue_endpoint']],
        ['both', 'orders', ['orders', 'events', 'orders_daily', 'revenue_endpoint']],
    ])('walks %s from %s', (mode, start, expected) => {
        const reached = traverseLineage(start, buildAdjacencyMaps(EDGES), mode as LineageSearchMode)
        expect([...reached].sort()).toEqual([...expected].sort())
    })

    it('does not reach a sibling through a shared parent', () => {
        // events feeds both orders and a sibling. From orders, `both` must never reach the sibling.
        const maps = buildAdjacencyMaps([...EDGES, edge('events', 'sessions')])

        expect(traverseLineage('orders', maps, 'both').has('sessions')).toBe(false)
    })

    it('walks a broad cyclic graph without visiting nodes twice', () => {
        const branches = Array.from({ length: 100 }, (_, index) => node(`branch-${index}`, `branch-${index}`))
        const nodes = [node('root', 'root'), ...branches, node('terminal', 'terminal')]
        const edges = [
            ...branches.flatMap((branch) => [edge('root', branch.id), edge(branch.id, 'terminal')]),
            edge('terminal', 'root'),
        ]

        const reached = traverseLineage('root', buildAdjacencyMaps(edges), 'downstream')
        expect(reached).toEqual(new Set(nodes.map(({ id }) => id)))

        const ordered = orderedNodesForLineageSearch(nodes, edges, parseLineageSearch('root+'))
        expect(ordered).toHaveLength(nodes.length)
        expect(ordered?.[0].id).toEqual('root')
        expect(ordered?.at(-1)?.id).toEqual('terminal')
    })

    it('anchors on the exact name over a longer one that contains it', () => {
        const nodes = [node('1', 'orders_daily'), node('2', 'orders'), node('3', 'stripe_orders_raw')]
        expect(matchNodesByName(nodes, 'orders')[0].name).toEqual('orders')
    })

    describe('orderedNodesForLineageSearch', () => {
        it('orders the anchor first, then models by distance and name', () => {
            const nodes = [node('root', 'root'), node('zeta', 'zeta'), node('alpha', 'alpha'), node('leaf', 'leaf')]
            const edges = [edge('root', 'zeta'), edge('root', 'alpha'), edge('alpha', 'leaf')]

            expect(
                orderedNodesForLineageSearch(nodes, edges, parseLineageSearch('root+'))?.map(({ name }) => name)
            ).toEqual(['root', 'alpha', 'zeta', 'leaf'])
        })

        it('keeps bidirectional walks from reaching siblings', () => {
            const nodes = ['events', 'orders', 'sessions'].map((name) => node(name, name))
            const edges = [edge('events', 'orders'), edge('events', 'sessions')]

            expect(
                orderedNodesForLineageSearch(nodes, edges, parseLineageSearch('+orders+'))?.map(({ name }) => name)
            ).toEqual(['orders', 'events'])
        })
    })

    describe('nodeIdsForLineageSearch', () => {
        // EDGES is keyed by name, so the fixture names each node after its id.
        const nodes = ['events', 'orders', 'orders_daily', 'revenue_endpoint'].map((name) => node(name, name))

        it('returns null for a plain term, so a name search highlights instead of pruning', () => {
            expect(nodeIdsForLineageSearch(nodes, EDGES, parseLineageSearch('orders'))).toBeNull()
        })

        it('prunes to nothing when the anchor names no model', () => {
            expect(nodeIdsForLineageSearch(nodes, EDGES, parseLineageSearch('+nope'))?.size).toEqual(0)
        })

        it('prunes to the cone of an anchored term', () => {
            const reached = nodeIdsForLineageSearch(nodes, EDGES, parseLineageSearch('+orders_daily'))
            expect([...(reached ?? [])].sort()).toEqual(['events', 'orders', 'orders_daily'])
        })
    })

    it('drops edges that lost an endpoint to filtering', () => {
        expect(edgesWithinNodes(EDGES, new Set(['events', 'orders']))).toEqual([edge('events', 'orders')])
    })
})
