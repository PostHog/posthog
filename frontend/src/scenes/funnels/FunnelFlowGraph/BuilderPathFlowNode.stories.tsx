import { Meta, StoryObj } from '@storybook/react'
import { NodeTypes } from '@xyflow/react'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { NodeCanvas, pathNode } from './__mocks__/nodeStoryUtils'
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

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        const data: PathFlowNodeData = { eventName: '$pageview', displayName: '/pricing', count: 42 }
        return (
            <NodeCanvas
                nodes={[pathNode('p1', 'pathShell', data, 0)]}
                nodeTypes={defaultNodeTypes}
                height={100}
                padding={0.5}
            />
        )
    },
}

export const WithAddButton: Story = {
    render: () => {
        const data: PathFlowNodeData = { eventName: '$pageview', displayName: '/pricing', count: 42 }
        return (
            <NodeCanvas
                nodes={[pathNode('p1', 'builderPath', data, 0)]}
                nodeTypes={addableNodeTypes}
                height={100}
                padding={0.5}
            />
        )
    },
}

export const AllVariants: Story = {
    render: () => {
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
        return <NodeCanvas nodes={nodes} nodeTypes={mergedNodeTypes} height={100} />
    },
}
