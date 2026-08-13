import type { Meta, StoryObj } from '@storybook/react'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { LineageGraph } from './LineageGraph'

function mockNode(
    partial: Pick<DataModelingNode, 'id' | 'name' | 'type'> & Partial<DataModelingNode>
): DataModelingNode {
    return {
        dag: 'dag-1',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        upstream_count: 0,
        downstream_count: 0,
        ...partial,
    }
}

function mockEdge(id: string, sourceId: string, targetId: string): DataModelingEdge {
    return {
        id,
        source_id: sourceId,
        target_id: targetId,
        dag: 'dag-1',
        properties: {},
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
    }
}

const GRAPH_NODES: DataModelingNode[] = [
    mockNode({ id: '1', name: 'orders', type: 'table' }),
    mockNode({ id: '2', name: 'customers', type: 'table' }),
    mockNode({
        id: '3',
        name: 'revenue_summary',
        type: 'matview',
        last_run_at: '2024-01-15T10:30:00Z',
        last_run_status: 'Completed',
        sync_interval: '1hour',
    }),
    mockNode({ id: '4', name: 'monthly_report', type: 'view' }),
]
const GRAPH_EDGES: DataModelingEdge[] = [mockEdge('e1', '1', '3'), mockEdge('e2', '2', '3'), mockEdge('e3', '3', '4')]

type Story = StoryObj<typeof LineageGraph>
const meta: Meta<typeof LineageGraph> = {
    title: 'Products/Data modeling/Lineage graph',
    component: LineageGraph,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
    decorators: [
        (StoryFn) => (
            <div className="h-[500px]">
                <StoryFn />
            </div>
        ),
    ],
}

export default meta

export const Full: Story = {
    render: () => (
        <LineageGraph nodes={GRAPH_NODES} edges={GRAPH_EDGES} currentNodeId="4" variant="full" showControls />
    ),
}

export const Canvas: Story = {
    render: () => (
        <LineageGraph nodes={GRAPH_NODES} edges={GRAPH_EDGES} variant="canvas" showControls showMinimap interactive />
    ),
}

export const SingleNode: Story = {
    render: () => <LineageGraph nodes={[mockNode({ id: '1', name: 'raw_events', type: 'table' })]} edges={[]} />,
}

export const EmptyState: Story = {
    render: () => (
        <LineageGraph nodes={[]} edges={[]} emptyMessage="This query doesn't depend on any other tables or views" />
    ),
}
