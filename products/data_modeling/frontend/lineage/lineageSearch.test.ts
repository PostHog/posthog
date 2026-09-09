import { DataModelingEdge, DataModelingNode } from '~/types'

import {
    LineageSearchMode,
    buildAdjacencyMaps,
    edgesWithinNodes,
    matchNodesByName,
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

    it('anchors on the exact name over a longer one that contains it', () => {
        const nodes = [node('1', 'orders_daily'), node('2', 'orders'), node('3', 'stripe_orders_raw')]
        expect(matchNodesByName(nodes, 'orders')[0].name).toEqual('orders')
    })

    it('drops edges that lost an endpoint to filtering', () => {
        expect(edgesWithinNodes(EDGES, new Set(['events', 'orders']))).toEqual([edge('events', 'orders')])
    })
})
