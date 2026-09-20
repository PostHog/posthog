import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'

import { ModelsLineageTab } from 'scenes/models/tabs/ModelsLineageTab'

import { mswDecorator } from '~/mocks/browser'
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

const lineageTabDecorators = [
    mswDecorator({
        get: {
            '/api/environments/:team_id/data_modeling_nodes/': { count: GRAPH_NODES.length, results: GRAPH_NODES },
            '/api/environments/:team_id/data_modeling_edges/': { count: GRAPH_EDGES.length, results: GRAPH_EDGES },
        },
    }),
]

async function searchLineage(canvasElement: HTMLElement, term: string): Promise<HTMLElement> {
    const canvas = within(canvasElement)
    await canvas.findByText('monthly_report')
    const search = canvas.getByPlaceholderText('Search, or +name for upstream')
    fireEvent.change(search, { target: { value: term } })
    return canvasElement.querySelector<HTMLElement>('.react-flow')!
}

export const SearchFocus: Story = {
    render: () => <ModelsLineageTab />,
    decorators: lineageTabDecorators,
    play: async ({ canvasElement }) => {
        const graph = await searchLineage(canvasElement, 'monthly_report')
        const target = graph.querySelector<HTMLElement>('.react-flow__node[data-id="4"]')!
        await waitFor(() => {
            const nodeBounds = target.getBoundingClientRect()
            const graphBounds = graph.getBoundingClientRect()
            if (
                Math.abs(nodeBounds.x + nodeBounds.width / 2 - graphBounds.x - graphBounds.width / 2) > 5 ||
                Math.abs(nodeBounds.y + nodeBounds.height / 2 - graphBounds.y - graphBounds.height / 2) > 5
            ) {
                throw new Error('The search match must be centered in the lineage viewport')
            }
        })
        if (graph.querySelectorAll('.react-flow__node').length !== GRAPH_NODES.length) {
            throw new Error('Plain search must keep the rest of the graph visible')
        }
    },
}

export const SearchDimsNonMatches: Story = {
    render: () => <ModelsLineageTab />,
    decorators: lineageTabDecorators,
    play: async ({ canvasElement }) => {
        // A typo, so this also proves the match survives an imperfect name.
        const graph = await searchLineage(canvasElement, 'monthly_reprot')
        await waitFor(() => {
            if (!graph.querySelector('.react-flow__node[data-id="4"] .ring-2')) {
                throw new Error('The match must keep its ring')
            }
            if (graph.querySelectorAll('.react-flow__node .opacity-25').length !== GRAPH_NODES.length - 1) {
                throw new Error('Every model but the match must be dimmed')
            }
        })
        await within(canvasElement).findByText('Highlighting 1 of 4 models')
    },
}

export const SearchWithNoMatch: Story = {
    render: () => <ModelsLineageTab />,
    decorators: lineageTabDecorators,
    play: async ({ canvasElement }) => {
        const graph = await searchLineage(canvasElement, 'zzzqqq')
        await within(canvasElement).findByText('No models match your search')
        if (graph.querySelector('.react-flow__node .opacity-25')) {
            throw new Error('A search that matched nothing must not dim the whole graph')
        }
    },
}
