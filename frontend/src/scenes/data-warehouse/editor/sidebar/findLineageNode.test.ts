import { DataModelingNode } from '~/types'

import { findLineageNode } from './findLineageNode'

const node = (overrides: Partial<DataModelingNode>): DataModelingNode =>
    ({ id: 'node', name: 'name', type: 'view', ...overrides }) as DataModelingNode

describe('findLineageNode', () => {
    const nodes = [
        node({ id: 'view-node', name: 'events', type: 'view', saved_query_id: 'sq-1' }),
        node({ id: 'matview-node', name: 'daily', type: 'matview', saved_query_id: 'sq-2' }),
        node({ id: 'posthog-table-node', name: 'events', type: 'table', origin: 'posthog' }),
        node({
            id: 'warehouse-table-node',
            name: 'events',
            type: 'table',
            origin: 'warehouse',
            warehouse_table_id: 'wt-1',
        }),
    ]

    it.each([
        ['view', { kind: 'saved_query', savedQueryId: 'sq-1' }, 'view-node'],
        ['matview', { kind: 'saved_query', savedQueryId: 'sq-2' }, 'matview-node'],
        ['warehouse table', { kind: 'warehouse_table', warehouseTableId: 'wt-1' }, 'warehouse-table-node'],
        [
            'posthog table sharing a name with a view',
            { kind: 'posthog_table', tableName: 'events' },
            'posthog-table-node',
        ],
        ['unknown view', { kind: 'saved_query', savedQueryId: 'missing' }, undefined],
    ] as const)('resolves a %s', (_, target, expectedId) => {
        expect(findLineageNode(nodes, target)?.id).toEqual(expectedId)
    })
})
