import { DataModelingEdge, DataModelingNode } from '~/types'

import {
    LineageSearchMode,
    buildAdjacencyMaps,
    edgesWithinNodes,
    matchNodes,
    nodeIdsForLineageSearch,
    parseLineageSearch,
    traverseLineage,
} from './lineageSearch'

const node = (id: string, name: string, extra: Partial<DataModelingNode> = {}): DataModelingNode =>
    ({ id, name, type: 'view', ...extra }) as DataModelingNode
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

    describe('matchNodes', () => {
        const nodes = [
            node('1', 'orders_daily'),
            node('2', 'orders'),
            node('3', 'stripe_orders_raw'),
            node('4', 'sessions', { dag_name: 'Marketing', user_tag: 'nightly' }),
        ]

        it('anchors on the exact name over a longer one that contains it', () => {
            expect(matchNodes(nodes, 'orders')[0].name).toEqual('orders')
        })

        it.each([
            ['a typo', 'ordrs', 'orders'],
            ['the DAG name', 'marketing', 'sessions'],
            ['the tag', 'nightly', 'sessions'],
        ])('matches on %s', (_label, term, expected) => {
            expect(matchNodes(nodes, term).map((n) => n.name)).toContain(expected)
        })

        it('keeps a name hit above a fuzzy hit that scores better elsewhere', () => {
            expect(
                matchNodes(nodes, 'orders')
                    .map((n) => n.name)
                    .slice(0, 3)
            ).toEqual(['orders', 'orders_daily', 'stripe_orders_raw'])
        })

        it('matches nothing for a term no model resembles', () => {
            expect(matchNodes(nodes, 'zzzqqq')).toEqual([])
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
