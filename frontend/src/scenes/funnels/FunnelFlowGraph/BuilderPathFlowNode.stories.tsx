import '@xyflow/react/dist/style.css'

import { Meta, StoryFn } from '@storybook/react'
import { Node, NodeTypes, ReactFlow, ReactFlowProvider } from '@xyflow/react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { PathFlowNodeShell } from './PathFlowNode'
import { PathFlowNodeData, PATH_NODE_WIDTH } from './pathFlowUtils'

function BuilderPathNode({ data, id }: { data: PathFlowNodeData; id: string }): JSX.Element {
    return (
        <PathFlowNodeShell id={id} data={data}>
            <LemonButton size="xsmall" icon={<IconPlus />} className="ml-1 shrink-0" tooltip="Add as funnel step" />
        </PathFlowNodeShell>
    )
}

const defaultNodeTypes: NodeTypes = {
    pathShell: ({ data, id }: { data: PathFlowNodeData; id: string }) => <PathFlowNodeShell id={id} data={data} />,
}

const addableNodeTypes: NodeTypes = {
    builderPath: ({ data, id }: { data: PathFlowNodeData; id: string }) => <BuilderPathNode id={id} data={data} />,
}

function pathNode(id: string, type: string, data: PathFlowNodeData, x: number): Node {
    return {
        id,
        type,
        data,
        position: { x, y: 0 },
        draggable: false,
        connectable: false,
    }
}

const meta: Meta = {
    title: 'Scenes-App/Customer Analytics/Journeys/Nodes/BuilderPathFlowNode',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2024-01-15',
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}
export default meta

export const Default: StoryFn = () => {
    const data: PathFlowNodeData = { eventName: '$pageview', displayName: '/pricing', count: 42 }
    return (
        <ReactFlowProvider>
            <div style={{ width: '100%', height: 100 }}>
                <ReactFlow
                    nodes={[pathNode('p1', 'pathShell', data, 0)]}
                    edges={[]}
                    nodeTypes={defaultNodeTypes}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    fitView
                    fitViewOptions={{ padding: 0.5 }}
                    proOptions={{ hideAttribution: true }}
                    minZoom={0.5}
                    maxZoom={1}
                />
            </div>
        </ReactFlowProvider>
    )
}

export const WithAddButton: StoryFn = () => {
    const data: PathFlowNodeData = { eventName: '$pageview', displayName: '/pricing', count: 42 }
    return (
        <ReactFlowProvider>
            <div style={{ width: '100%', height: 100 }}>
                <ReactFlow
                    nodes={[pathNode('p1', 'builderPath', data, 0)]}
                    edges={[]}
                    nodeTypes={addableNodeTypes}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    fitView
                    fitViewOptions={{ padding: 0.5 }}
                    proOptions={{ hideAttribution: true }}
                    minZoom={0.5}
                    maxZoom={1}
                />
            </div>
        </ReactFlowProvider>
    )
}

export const AllVariants: StoryFn = () => {
    const spacing = PATH_NODE_WIDTH + 30
    const mergedNodeTypes: NodeTypes = { ...defaultNodeTypes, ...addableNodeTypes }
    const nodes = [
        pathNode('p1', 'pathShell', { eventName: '$pageview', displayName: '/pricing', count: 150 }, 0),
        pathNode('p2', 'builderPath', { eventName: '$pageview', displayName: '/signup', count: 85 }, spacing),
        pathNode(
            'p3',
            'pathShell',
            { eventName: 'long_custom_event_name', displayName: 'long_custom_event_name', count: 3 },
            spacing * 2
        ),
    ]
    return (
        <ReactFlowProvider>
            <div style={{ width: '100%', height: 100 }}>
                <ReactFlow
                    nodes={nodes}
                    edges={[]}
                    nodeTypes={mergedNodeTypes}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    fitView
                    fitViewOptions={{ padding: 0.3 }}
                    proOptions={{ hideAttribution: true }}
                    minZoom={0.5}
                    maxZoom={1}
                />
            </div>
        </ReactFlowProvider>
    )
}
