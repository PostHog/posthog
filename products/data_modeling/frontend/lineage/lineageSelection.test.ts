import { DataModelingEdge } from '~/types'

import { lineageCone } from './lineageSelection'

const edge = (source_id: string, target_id: string): DataModelingEdge =>
    ({ id: `${source_id}>${target_id}`, source_id, target_id }) as DataModelingEdge

// events -> orders -> daily -> endpoint, with users joining orders and other branching off events
const EDGES = [
    edge('events', 'orders'),
    edge('users', 'orders'),
    edge('orders', 'daily'),
    edge('daily', 'endpoint'),
    edge('events', 'other'),
    // Both ends are related to orders, but this edge bypasses orders.
    edge('events', 'daily'),
]

describe('lineageCone', () => {
    it('selects the full lineage without siblings or bypass edges', () => {
        const cone = lineageCone(EDGES, 'orders')

        expect([...cone.nodeIds].sort()).toEqual(['daily', 'endpoint', 'events', 'orders', 'users'])
        expect([...cone.edgeIds].sort()).toEqual(['daily>endpoint', 'events>orders', 'orders>daily', 'users>orders'])
    })
})
