import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { claudeCodePluginSession } from '../sampleFixtures/claudeCodePluginSession'
import { FIXTURE_TREE, withWidth } from '../storyFixtures'
import { TraceTree } from './TraceTree'

function Stateful({
    nodes,
    initialSelectedId = 'gen-answer',
}: {
    nodes: TraceNodeApi[]
    initialSelectedId?: string
}): JSX.Element {
    const [selected, setSelected] = useState<string | null>(initialSelectedId)
    return <TraceTree nodes={nodes} selectedNodeId={selected} onSelectNode={setSelected} />
}

const meta: Meta<typeof Stateful> = {
    title: 'Scenes-App/AI observability/Trace view/Trace tree',
    component: Stateful,
    decorators: [withWidth(280)],
}
export default meta

type Story = StoryObj<typeof Stateful>

export const Default: Story = { args: { nodes: FIXTURE_TREE } }
export const DeepAgentTree: Story = {
    args: { nodes: claudeCodePluginSession.tree, initialSelectedId: claudeCodePluginSession.initialNodeId },
}
export const WithError: Story = {
    args: {
        nodes: [
            {
                ...FIXTURE_TREE[0],
                hasError: true,
                children: [{ ...FIXTURE_TREE[0].children[1], hasError: true }],
            },
        ],
    },
}
