import { DataModelingEdge, DataModelingNode } from '~/types'

import { LineageSelectionMode, lineageCone, scopeLineage } from './lineageSelection'

const edge = (source_id: string, target_id: string): DataModelingEdge =>
    ({ id: `${source_id}>${target_id}`, source_id, target_id }) as DataModelingEdge

// events -> orders -> daily -> endpoint, with `users` joining `orders` and `other` branching off `events`
const EDGES = [
    edge('events', 'orders'),
    edge('users', 'orders'),
    edge('orders', 'daily'),
    edge('daily', 'endpoint'),
    edge('events', 'other'),
    // bypasses `orders`: both ends are in the cone of `orders`, but the edge is not on its lineage
    edge('events', 'daily'),
]

describe('lineageCone', () => {
    it.each<[LineageSelectionMode, string[], string[]]>([
        ['upstream', ['orders', 'events', 'users'], ['events>orders', 'users>orders']],
        ['downstream', ['orders', 'daily', 'endpoint'], ['orders>daily', 'daily>endpoint']],
        [
            'both',
            ['orders', 'events', 'users', 'daily', 'endpoint'],
            ['events>orders', 'users>orders', 'orders>daily', 'daily>endpoint'],
        ],
    ])('selects %s of orders without siblings or bypass edges', (mode, nodeIds, edgeIds) => {
        const cone = lineageCone(EDGES, { nodeId: 'orders', mode })
        expect([...cone.nodeIds].sort()).toEqual([...nodeIds].sort())
        expect([...cone.edgeIds].sort()).toEqual([...edgeIds].sort())
    })
})

describe('scopeLineage', () => {
    const nodes = ['events', 'users', 'orders', 'daily', 'endpoint', 'other'].map(
        (id) => ({ id, name: id }) as DataModelingNode
    )

    it('keeps only the downstream cone and the edges on it', () => {
        const scoped = scopeLineage(nodes, EDGES, { nodeId: 'orders', mode: 'downstream' })
        expect(scoped?.nodes.map((n) => n.id)).toEqual(['orders', 'daily', 'endpoint'])
        expect(scoped?.edges.map((e) => e.id)).toEqual(['orders>daily', 'daily>endpoint'])
    })

    it.each([[null], [{ nodeId: 'gone', mode: 'both' as const }]])('leaves the graph whole for %j', (scope) => {
        expect(scopeLineage(nodes, EDGES, scope)).toBeNull()
    })
})
