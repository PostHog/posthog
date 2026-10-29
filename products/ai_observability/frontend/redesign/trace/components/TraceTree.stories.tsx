import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { TraceNodeApi } from '../../../generated/api.schemas'
import { claudeCodePluginSession } from '../sampleFixtures/claudeCodePluginSession'
import { FIXTURE_TREE, withWidth } from '../storyFixtures'
import { EvalRollupOutcome } from '../types'
import { TraceTree } from './TraceTree'

function Stateful({
    nodes,
    initialSelectedId = 'gen-answer',
    evalOutcomes = {},
    feedbackCountByNodeId,
}: {
    nodes: TraceNodeApi[]
    initialSelectedId?: string
    evalOutcomes?: Record<string, EvalRollupOutcome>
    feedbackCountByNodeId?: Record<string, number>
}): JSX.Element {
    const [selected, setSelected] = useState<string | null>(initialSelectedId)
    return (
        <TraceTree
            nodes={nodes}
            selectedNodeId={selected}
            onSelectNode={setSelected}
            onPrefetchNode={() => {}}
            evalOutcomes={evalOutcomes}
            feedbackCountByNodeId={feedbackCountByNodeId}
        />
    )
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
export const WithEvalMarkers: Story = {
    args: {
        nodes: FIXTURE_TREE,
        evalOutcomes: { 'trace-1': 'pass', 'embed-question': 'unrated', 'gen-answer': 'fail' },
    },
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
export const WithFeedbackMarkers: Story = {
    args: { nodes: FIXTURE_TREE, feedbackCountByNodeId: { 'trace-1': 3, 'gen-answer': 12, 'span-search': 1 } },
}
