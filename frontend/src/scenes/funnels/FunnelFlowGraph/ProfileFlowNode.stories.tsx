import '@xyflow/react/dist/style.css'

import { Meta, StoryObj } from '@storybook/react'
import { Node, NodeTypes } from '@xyflow/react'

import { FunnelStepWithConversionMetrics } from '~/types'

import { makeStep, NodeCanvas } from './__mocks__/nodeStoryUtils'
import { FunnelFlowNodeData, PROFILE_NODE_WIDTH } from './funnelFlowGraphLogic'
import { ProfileFlowNode } from './FunnelFlowNode'

const nodeTypes: NodeTypes = { profile: ProfileFlowNode }

function profileNode(
    id: string,
    step: FunnelStepWithConversionMetrics,
    stepIndex: number,
    isOptional: boolean,
    x: number
): Node<FunnelFlowNodeData> {
    return {
        id,
        type: 'profile',
        data: { step, stepIndex, isOptional },
        position: { x, y: 0 },
        draggable: false,
        connectable: false,
    }
}

const meta: Meta = {
    title: 'Scenes-App/Customer Analytics/Journeys/Nodes/ProfileFlowNode',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2024-01-15',
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}
export default meta

type Story = StoryObj<{}>

export const Completed: Story = {
    render: () => {
        const step = makeStep('Completed', 0, 100, 100)
        return <NodeCanvas nodes={[profileNode('n', step, 0, false, 0)]} nodeTypes={nodeTypes} />
    },
}

export const NotCompleted: Story = {
    render: () => {
        const step = makeStep('Not completed', 1, 0, 100)
        return <NodeCanvas nodes={[profileNode('n', step, 1, false, 0)]} nodeTypes={nodeTypes} />
    },
}

export const OptionalCompleted: Story = {
    render: () => {
        const step = makeStep('Optional completed', 1, 1, 100)
        return <NodeCanvas nodes={[profileNode('n', step, 1, true, 0)]} nodeTypes={nodeTypes} />
    },
}

export const OptionalNotCompleted: Story = {
    render: () => {
        const step = makeStep('Optional not completed', 3, 0, 100)
        return <NodeCanvas nodes={[profileNode('n', step, 3, true, 0)]} nodeTypes={nodeTypes} />
    },
}

export const AllVariants: Story = {
    render: () => {
        const spacing = PROFILE_NODE_WIDTH + 40
        const nodes = [
            profileNode('s0', makeStep('Completed', 0, 1, 1), 0, false, 0),
            profileNode('s1', makeStep('Not completed', 1, 0, 1), 1, false, spacing),
            profileNode('s2', makeStep('Optional completed', 2, 1, 1), 2, true, spacing * 2),
            profileNode('s3', makeStep('Optional not completed', 3, 0, 1), 3, true, spacing * 3),
        ]
        return <NodeCanvas nodes={nodes} nodeTypes={nodeTypes} />
    },
}
