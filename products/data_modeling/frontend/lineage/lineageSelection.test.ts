import { DataModelingEdge } from '~/types'

import { LineageSelectionMode, lineageCone } from './lineageSelection'

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
