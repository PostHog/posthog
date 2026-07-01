import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { DataModelingEdge, DataModelingNode } from '~/types'

import { sqlEditorLogic } from '../../sqlEditorLogic'
import { UpstreamGraph } from './UpstreamGraph'

interface MockLineage {
    nodes: DataModelingNode[]
    edges: DataModelingEdge[]
}

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

const MOCK_LINEAGE_WITH_GRAPH: MockLineage = {
    nodes: [
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
    ],
    edges: [mockEdge('e1', '1', '3'), mockEdge('e2', '2', '3'), mockEdge('e3', '3', '4')],
}

const MOCK_LINEAGE_SINGLE_NODE: MockLineage = {
    nodes: [mockNode({ id: '1', name: 'raw_events', type: 'table' })],
    edges: [],
}

const TAB_ID = 'story-tab'

function GraphLoader({ lineage }: { lineage: MockLineage }): JSX.Element {
    const { loadUpstreamSuccess } = useActions(sqlEditorLogic({ tabId: TAB_ID }))
    useDelayedOnMountEffect(() => loadUpstreamSuccess(lineage))
    return <UpstreamGraph tabId={TAB_ID} />
}

type Story = StoryObj<typeof UpstreamGraph>
const meta: Meta<typeof UpstreamGraph> = {
    title: 'Scenes-App/Data Warehouse/Editor/Upstream graph',
    component: UpstreamGraph,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
}

export default meta

export const WithGraph: Story = {
    render: () => <GraphLoader lineage={MOCK_LINEAGE_WITH_GRAPH} />,
}

export const SingleNode: Story = {
    render: () => <GraphLoader lineage={MOCK_LINEAGE_SINGLE_NODE} />,
}

export const EmptyState: Story = {
    render: () => <UpstreamGraph tabId={TAB_ID} />,
}
