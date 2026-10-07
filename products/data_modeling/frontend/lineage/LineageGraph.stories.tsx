import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import type { XYPosition } from '@xyflow/react'
import { MakeLogicType, actions, kea, path, reducers, useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { LineageGraph } from './LineageGraph'
import { ModelsLineageTab } from './ModelsLineageTab'

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
    mockNode({ id: '5', name: 'weekly_active_accounts', type: 'metric', metric_id: 'metric-1' }),
    mockNode({
        id: '6',
        name: 'monthly_recurring_revenue',
        type: 'metric',
        metric_id: 'metric-2',
        lineage_issue: { kind: 'unresolved', detail: 'legacy_orders', at: '2024-01-15T10:30:00Z' },
    }),
]
const GRAPH_EDGES: DataModelingEdge[] = [
    mockEdge('e1', '1', '3'),
    mockEdge('e2', '2', '3'),
    mockEdge('e3', '3', '4'),
    mockEdge('e4', '3', '5'),
    mockEdge('e5', '4', '6'),
]

const MOVED_NODE_POSITIONS: Record<string, XYPosition> = { '6': { x: 1500, y: 700 } }

interface DraggableLineageGraphStoryLogicValues {
    nodePositions: Record<string, XYPosition>
}

interface DraggableLineageGraphStoryLogicActions {
    nodeDragStopped: (nodeId: string, position: XYPosition) => { nodeId: string; position: XYPosition }
    resetNodePositions: () => Record<string, never>
}

type DraggableLineageGraphStoryLogicType = MakeLogicType<
    DraggableLineageGraphStoryLogicValues,
    DraggableLineageGraphStoryLogicActions
>

const draggableLineageGraphStoryLogic = kea<DraggableLineageGraphStoryLogicType>([
    path(['products', 'data_modeling', 'lineage', 'draggableLineageGraphStoryLogic']),
    actions({
        nodeDragStopped: (nodeId: string, position: XYPosition) => ({ nodeId, position }),
        resetNodePositions: true,
    }),
    reducers({
        nodePositions: [
            MOVED_NODE_POSITIONS,
            {
                nodeDragStopped: (positions, { nodeId, position }) => ({ ...positions, [nodeId]: position }),
                resetNodePositions: () => ({}),
            },
        ],
    }),
])

function DraggableLineageGraphStory({ focusMovedNode = false }: { focusMovedNode?: boolean }): JSX.Element {
    const { nodePositions } = useValues(draggableLineageGraphStoryLogic)
    const { nodeDragStopped, resetNodePositions } = useActions(draggableLineageGraphStoryLogic)

    return (
        <LineageGraph
            nodes={GRAPH_NODES}
            edges={GRAPH_EDGES}
            variant="canvas"
            interactive
            nodesDraggable
            nodePositions={nodePositions}
            onNodeDragStop={(node, position) => nodeDragStopped(node.id, position)}
            onResetNodePositions={resetNodePositions}
            searchFocusRequest={focusMovedNode ? { nodeId: '6', requestId: 1 } : undefined}
            showControls
            showMinimap
        />
    )
}

// Pruning the graph rekeys `lineageGraphLogic`, so react-flow unmounts while ELK lays the cone
// out again. Read the canvas on every poll — a node captured before the relayout is detached,
// and a detached element reports a zero-sized rect that passes any centering check.
const VIEWPORT_SETTLE_MS = 10000

async function expectNodeCentered(canvasElement: HTMLElement, nodeId: string, message: string): Promise<void> {
    await waitFor(
        () => {
            const graph = canvasElement.querySelector<HTMLElement>('.react-flow')
            const node = graph?.querySelector<HTMLElement>(`.react-flow__node[data-id="${nodeId}"]`)
            if (!graph || !node) {
                throw new Error(message)
            }
            const nodeBounds = node.getBoundingClientRect()
            const graphBounds = graph.getBoundingClientRect()
            if (
                Math.abs(nodeBounds.x + nodeBounds.width / 2 - graphBounds.x - graphBounds.width / 2) > 5 ||
                Math.abs(nodeBounds.y + nodeBounds.height / 2 - graphBounds.y - graphBounds.height / 2) > 5
            ) {
                throw new Error(message)
            }
        },
        { timeout: VIEWPORT_SETTLE_MS }
    )
}

async function expectNodesCentered(canvasElement: HTMLElement, message: string): Promise<void> {
    await waitFor(
        () => {
            const graph = canvasElement.querySelector<HTMLElement>('.react-flow')
            const nodes = [...(graph?.querySelectorAll<HTMLElement>('.react-flow__node') ?? [])]
            if (!graph || nodes.length < 2) {
                throw new Error(message)
            }
            const nodeBounds = nodes.map((node) => node.getBoundingClientRect())
            const left = Math.min(...nodeBounds.map((bounds) => bounds.left))
            const right = Math.max(...nodeBounds.map((bounds) => bounds.right))
            const top = Math.min(...nodeBounds.map((bounds) => bounds.top))
            const bottom = Math.max(...nodeBounds.map((bounds) => bounds.bottom))
            const graphBounds = graph.getBoundingClientRect()
            if (
                Math.abs((left + right) / 2 - (graphBounds.left + graphBounds.right) / 2) > 5 ||
                Math.abs((top + bottom) / 2 - (graphBounds.top + graphBounds.bottom) / 2) > 5
            ) {
                throw new Error(message)
            }
        },
        { timeout: VIEWPORT_SETTLE_MS }
    )
}

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
            <div className="h-[500px] w-[1200px]">
                <StoryFn />
            </div>
        ),
    ],
}

export default meta

// The loading graph keeps its skeleton nodes on screen, so the test runner must not wait for them to go.
const LOADING_PARAMETERS = {
    testOptions: { waitForLoadersToDisappear: false, waitForSelector: '.react-flow__node' },
}

export const Full: Story = {
    render: () => (
        <LineageGraph nodes={GRAPH_NODES} edges={GRAPH_EDGES} currentNodeId="4" variant="full" showControls />
    ),
}

const INSIGHT_READER_NODES: DataModelingNode[] = [
    mockNode({ id: '1', name: 'orders', type: 'table' }),
    mockNode({ id: '4', name: 'monthly_report', type: 'view' }),
    mockNode({ id: '7', name: 'Monthly revenue', type: 'insight', insight_id: 101, insight_short_id: 'AbC123xY' }),
]
const INSIGHT_READER_EDGES: DataModelingEdge[] = [mockEdge('e1', '1', '4'), mockEdge('e6', '4', '7')]

export const ViewReadByInsight: Story = {
    render: () => (
        <LineageGraph
            nodes={INSIGHT_READER_NODES}
            edges={INSIGHT_READER_EDGES}
            currentNodeId="4"
            variant="full"
            showControls
        />
    ),
}

export const Canvas: Story = {
    render: () => (
        <LineageGraph nodes={GRAPH_NODES} edges={GRAPH_EDGES} variant="canvas" showControls showMinimap interactive />
    ),
}

export const Selectable: Story = {
    render: () => <LineageGraph nodes={GRAPH_NODES} edges={GRAPH_EDGES} variant="canvas" selectable interactive />,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const selectedNode = (await canvas.findByText('monthly_report')).closest<HTMLElement>(
            '[data-attr="lineage-node"]'
        )
        const relatedNode = canvas.getByText('orders').closest<HTMLElement>('[data-attr="lineage-node"]')
        const siblingNode = canvas
            .getByText('weekly_active_accounts')
            .closest<HTMLElement>('[data-attr="lineage-node"]')
        const pane = canvasElement.querySelector<HTMLElement>('.react-flow__pane')

        if (!selectedNode || !relatedNode || !siblingNode || !pane) {
            throw new Error('The selectable graph must render its nodes and pane')
        }

        fireEvent.click(selectedNode)
        await waitFor(() => {
            if (!selectedNode.classList.contains('ring-4')) {
                throw new Error('The clicked node must show the selected state')
            }
            if (relatedNode.classList.contains('opacity-30')) {
                throw new Error('An upstream node must stay highlighted')
            }
            if (!siblingNode.classList.contains('opacity-30')) {
                throw new Error('A node outside the selected lineage must be dimmed')
            }
        })

        fireEvent.click(pane)
        await waitFor(() => {
            if (siblingNode.classList.contains('opacity-30')) {
                throw new Error('Clicking the canvas must clear the lineage selection')
            }
        })
    },
}

// The minimap is gated on the canvas container instead of the viewport, so a canvas that is narrow
// inside a wide window must still hide it and leave the zoom controls room. The graph is cut to two
// nodes because fit-view scales the whole graph into 480px, and nodes that small render text the
// snapshot cannot compare reliably.
export const NarrowCanvas: Story = {
    render: () => (
        <LineageGraph
            nodes={GRAPH_NODES.slice(0, 2)}
            edges={[]}
            variant="canvas"
            showControls
            showMinimap
            interactive
        />
    ),
    decorators: [
        (StoryFn) => (
            <div className="h-[500px] w-[480px]">
                <StoryFn />
            </div>
        ),
    ],
}

const modelsTabDecorator = mswDecorator({
    get: {
        '/api/environments/:team_id/data_modeling_nodes/': { count: GRAPH_NODES.length, results: GRAPH_NODES },
        '/api/environments/:team_id/data_modeling_edges/': { count: GRAPH_EDGES.length, results: GRAPH_EDGES },
    },
})

export const DraggableNodes: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.DATA_MODELING_LINEAGE_NODE_DRAGGING] },
    render: () => <ModelsLineageTab />,
    decorators: [modelsTabDecorator],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const openButton = await canvas.findByLabelText('Open orders in new tab')
        const nodeCard = canvas.getByText('orders').closest<HTMLElement>('[data-attr="lineage-node"]')

        if (
            openButton.tagName !== 'A' ||
            !openButton.getAttribute('href') ||
            openButton.getAttribute('target') !== '_blank' ||
            !openButton.classList.contains('nodrag')
        ) {
            throw new Error('The explicit node link must open in a new tab')
        }
        if (!nodeCard || !nodeCard.classList.contains('cursor-grab')) {
            throw new Error('A draggable node must keep its drag affordance')
        }
        const selectionButton = within(nodeCard).getByRole('button', { name: /highlights its lineage/ })
        if (selectionButton.tabIndex < 0) {
            throw new Error('Lineage selection must be keyboard accessible')
        }
        if (getComputedStyle(openButton).opacity !== '0') {
            throw new Error('The open link must stay hidden until the node has hover or focus')
        }

        selectionButton.focus()
        await waitFor(() => {
            if (getComputedStyle(openButton).opacity !== '1') {
                throw new Error('Keyboard focus must reveal the open link')
            }
        })
        selectionButton.blur()
        await waitFor(() => {
            if (getComputedStyle(openButton).opacity !== '0') {
                throw new Error('The open link must hide after the node loses focus')
            }
        })
    },
}

// The play function leaves the menu open, so this story takes no snapshot. Opening the menu in
// DraggableNodes instead would paint it over that story's picture on every run.
export const NodeMenu: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.DATA_MODELING_LINEAGE_NODE_DRAGGING],
        testOptions: { snapshotBrowsers: [] },
    },
    render: () => <ModelsLineageTab />,
    decorators: [modelsTabDecorator],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const nodeCard = (await canvas.findByText('orders')).closest<HTMLElement>('[data-attr="lineage-node"]')

        if (!nodeCard) {
            throw new Error('A node must render as a card')
        }

        fireEvent.contextMenu(nodeCard)
        const page = within(canvasElement.ownerDocument.body)
        await page.findByRole('menuitem', { name: 'Open in new tab' })
        await page.findByRole('menuitem', { name: 'Copy name' })
        if (page.queryByText(/Highlight|Show only/)) {
            throw new Error('The node menu must not duplicate the graph lineage behavior')
        }
    },
}

export const MovedNodeFocus: Story = {
    render: () => <DraggableLineageGraphStory focusMovedNode />,
    play: async ({ canvasElement }) => {
        await expectNodeCentered(canvasElement, '6', 'Search focus must center the moved node, not its ELK position')
    },
}

export const ResetMovedNodes: Story = {
    render: () => <DraggableLineageGraphStory />,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('monthly_recurring_revenue')
        fireEvent.click(canvas.getByLabelText('Reset layout'))
        await expectNodesCentered(canvasElement, 'Reset layout must restore and center the ELK positions')
    },
}

export const Loading: Story = {
    parameters: LOADING_PARAMETERS,
    render: () => (
        <LineageGraph
            nodes={GRAPH_NODES}
            edges={GRAPH_EDGES}
            loading
            variant="canvas"
            showControls
            showMinimap
            panels={<span>Graph tools</span>}
        />
    ),
    play: async ({ canvasElement }) => {
        await expectNodesCentered(canvasElement, 'The loading skeleton must be centered in the lineage viewport')
    },
}

export const LoadingFocused: Story = {
    parameters: LOADING_PARAMETERS,
    render: () => (
        <LineageGraph
            nodes={GRAPH_NODES}
            edges={GRAPH_EDGES}
            loading
            loadingCenter={{ name: 'revenue_summary', type: 'matview' }}
            variant="full"
            showControls
            showMinimap
            panels={<span>Graph tools</span>}
        />
    ),
    play: async ({ canvasElement }) => {
        await expectNodesCentered(
            canvasElement,
            'The focused loading skeleton must be centered in the lineage viewport'
        )
    },
}

export const LoadingDarkMode: Story = {
    ...LoadingFocused,
    globals: { theme: 'dark' },
}

export const SingleNode: Story = {
    render: () => <LineageGraph nodes={[mockNode({ id: '1', name: 'raw_events', type: 'table' })]} edges={[]} />,
}

export const EmptyState: Story = {
    render: () => (
        <LineageGraph nodes={[]} edges={[]} emptyMessage="This query doesn't depend on any other tables or views" />
    ),
}

export const SearchFocus: Story = {
    render: () => <ModelsLineageTab />,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': { count: GRAPH_NODES.length, results: GRAPH_NODES },
                '/api/environments/:team_id/data_modeling_edges/': { count: GRAPH_EDGES.length, results: GRAPH_EDGES },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('monthly_report')
        const search = canvas.getByPlaceholderText('Search, or +name for upstream')
        fireEvent.change(search, { target: { value: 'monthly' } })
        await canvas.findByText('2 results')
        fireEvent.keyDown(search, { key: 'ArrowDown' })
        // The arrow key moves the selection through a kea listener, so the new result is only
        // selected on the next tick. Pressing Enter in the same tick would focus the old one.
        await canvas.findByText('monthly_recurring_revenue, result 2 of 2')
        fireEvent.keyDown(search, { key: 'Enter' })
        await expectNodeCentered(canvasElement, '6', 'The search match must be centered in the lineage viewport')
        const graph = canvasElement.querySelector<HTMLElement>('.react-flow')!
        if (graph.querySelectorAll('.react-flow__node').length !== GRAPH_NODES.length) {
            throw new Error('Plain search must keep the rest of the graph visible')
        }

        fireEvent.change(search, { target: { value: '' } })
        await expectNodesCentered(canvasElement, 'Clearing search must fit the whole graph')
        fireEvent.change(search, { target: { value: 'monthly' } })
        await canvas.findByText('2 results')
        fireEvent.keyDown(search, { key: 'ArrowDown' })
        await canvas.findByText('monthly_recurring_revenue, result 2 of 2')
        fireEvent.keyDown(search, { key: 'Enter' })
        await expectNodeCentered(canvasElement, '6', 'Repeated search focus must center the requested node')

        const previousResult = canvas.getByLabelText('Previous result')
        previousResult.focus()
        fireEvent.click(previousResult)
        if (document.activeElement !== search) {
            throw new Error('Cycling results must return focus to the search input')
        }
    },
}

export const SelectorFocus: Story = {
    render: () => <ModelsLineageTab />,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': { count: GRAPH_NODES.length, results: GRAPH_NODES },
                '/api/environments/:team_id/data_modeling_edges/': { count: GRAPH_EDGES.length, results: GRAPH_EDGES },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('revenue_summary')
        const search = canvas.getByPlaceholderText('Search, or +name for upstream')
        fireEvent.change(search, { target: { value: 'revenue_summary+' } })
        await canvas.findByText('4 models · downstream')
        fireEvent.keyDown(search, { key: 'ArrowDown' })
        await canvas.findByText('monthly_report, result 2 of 4')
        fireEvent.keyDown(search, { key: 'Enter' })
        if ((search as HTMLInputElement).selectionStart !== 'revenue_summary'.length) {
            throw new Error('A downstream selector must keep the caret before its trailing plus')
        }
        await waitFor(
            () => {
                const graph = canvasElement.querySelector<HTMLElement>('.react-flow')
                if (!graph || graph.querySelectorAll('.react-flow__node').length !== 4) {
                    throw new Error('A downstream selector must keep only its lineage cone visible')
                }
            },
            { timeout: VIEWPORT_SETTLE_MS }
        )
        await expectNodeCentered(
            canvasElement,
            '4',
            'The selected downstream model must be centered in the lineage viewport'
        )
    },
}

export const DarkMode: Story = {
    render: () => (
        <LineageGraph nodes={GRAPH_NODES} edges={GRAPH_EDGES} currentNodeId="5" variant="full" showControls />
    ),
    globals: { theme: 'dark' },
}
