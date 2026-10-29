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
    matchingNodeIds = null,
}: {
    nodes: TraceNodeApi[]
    initialSelectedId?: string
    evalOutcomes?: Record<string, EvalRollupOutcome>
    matchingNodeIds?: ReadonlySet<string> | null
}): JSX.Element {
    const [selected, setSelected] = useState<string | null>(initialSelectedId)
    return (
        <TraceTree
            nodes={nodes}
            selectedNodeId={selected}
            onSelectNode={setSelected}
            onPrefetchNode={() => {}}
            evalOutcomes={evalOutcomes}
            matchingNodeIds={matchingNodeIds}
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
export const WithSearchMatches: Story = {
    args: { nodes: FIXTURE_TREE, matchingNodeIds: new Set(['span-search', 'gen-answer']) },
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
