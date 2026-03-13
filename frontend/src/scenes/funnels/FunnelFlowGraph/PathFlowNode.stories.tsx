import { Meta, StoryFn } from '@storybook/react'
import { NodeTypes } from '@xyflow/react'

import { IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'

import { NodeCanvas, pathNode } from './__mocks__/nodeStoryUtils'
import { PathFlowNodeShell } from './PathFlowNode'
import { PathFlowNodeData, PATH_NODE_WIDTH } from './pathFlowUtils'

function DefaultPathNode({ data, id }: { data: PathFlowNodeData; id: string }): JSX.Element {
    return <PathFlowNodeShell id={id} data={data} />
}

function AddablePathNode({ data, id }: { data: PathFlowNodeData; id: string }): JSX.Element {
    return (
        <PathFlowNodeShell id={id} data={data}>
            <LemonButton size="xsmall" icon={<IconPlus />} className="ml-1 shrink-0" tooltip="Add as funnel step" />
        </PathFlowNodeShell>
    )
}

function StagedPathNode({ data, id }: { data: PathFlowNodeData; id: string }): JSX.Element {
    return (
        <PathFlowNodeShell
            id={id}
            data={data}
            className="flex items-center rounded border border-success bg-success-highlight px-2 text-xs"
        >
            <More
                size="xsmall"
                className="ml-1 shrink-0"
                overlay={<LemonButton fullWidth>Make optional</LemonButton>}
            />
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                className="shrink-0"
                status="danger"
                tooltip="Remove from staged steps"
            />
        </PathFlowNodeShell>
    )
}

function StagedOptionalPathNode({ data, id }: { data: PathFlowNodeData; id: string }): JSX.Element {
    return (
        <PathFlowNodeShell
            id={id}
            data={data}
            className="flex items-center rounded border border-dashed border-success bg-success-highlight px-2 text-xs"
        >
            <More
                size="xsmall"
                className="ml-1 shrink-0"
                overlay={<LemonButton fullWidth>Make required</LemonButton>}
            />
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                className="shrink-0"
                status="danger"
                tooltip="Remove from staged steps"
            />
        </PathFlowNodeShell>
    )
}

const nodeTypes: NodeTypes = {
    path: ({ data, id }: { data: PathFlowNodeData; id: string }) => <DefaultPathNode data={data} id={id} />,
    addable: ({ data, id }: { data: PathFlowNodeData; id: string }) => <AddablePathNode data={data} id={id} />,
    staged: ({ data, id }: { data: PathFlowNodeData; id: string }) => <StagedPathNode data={data} id={id} />,
    stagedOptional: ({ data, id }: { data: PathFlowNodeData; id: string }) => (
        <StagedOptionalPathNode data={data} id={id} />
    ),
}

const sampleData: PathFlowNodeData = { eventName: '$pageview', displayName: '/home', count: 42 }

const meta: Meta = {
    title: 'Scenes-App/Customer Analytics/Journeys/Nodes/PathFlowNode',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2024-01-15',
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}
export default meta

export const Default: StoryFn = () => (
    <NodeCanvas nodes={[pathNode('p1', 'path', sampleData, 0)]} nodeTypes={nodeTypes} height={100} padding={0.5} />
)

export const LongEventName: StoryFn = () => (
    <NodeCanvas
        nodes={[
            pathNode(
                'p1',
                'path',
                {
                    eventName: 'custom_event_with_a_very_long_name',
                    displayName: 'custom_event_with_a_very_long_name',
                    count: 3,
                },
                0
            ),
        ]}
        nodeTypes={nodeTypes}
        height={100}
        padding={0.5}
    />
)

export const Addable: StoryFn = () => (
    <NodeCanvas nodes={[pathNode('p1', 'addable', sampleData, 0)]} nodeTypes={nodeTypes} height={100} padding={0.5} />
)

export const Staged: StoryFn = () => (
    <NodeCanvas nodes={[pathNode('p1', 'staged', sampleData, 0)]} nodeTypes={nodeTypes} height={100} padding={0.5} />
)

export const StagedOptional: StoryFn = () => (
    <NodeCanvas
        nodes={[pathNode('p1', 'stagedOptional', sampleData, 0)]}
        nodeTypes={nodeTypes}
        height={100}
        padding={0.5}
    />
)

export const AllVariants: StoryFn = () => {
    const spacing = PATH_NODE_WIDTH + 40
    const nodes = [
        pathNode('p1', 'path', { eventName: '$pageview', displayName: '/pricing', count: 150 }, 0),
        pathNode('p2', 'addable', { eventName: '$pageview', displayName: '/signup', count: 85 }, spacing),
        pathNode('p3', 'staged', { eventName: '$pageview', displayName: '/checkout', count: 42 }, spacing * 2),
        pathNode('p4', 'stagedOptional', { eventName: '$pageview', displayName: '/docs', count: 20 }, spacing * 3),
        pathNode(
            'p5',
            'path',
            { eventName: 'long_custom_event_name', displayName: 'long_custom_event_name', count: 3 },
            spacing * 4
        ),
    ]
    return <NodeCanvas nodes={nodes} nodeTypes={nodeTypes} height={100} padding={0.2} />
}
