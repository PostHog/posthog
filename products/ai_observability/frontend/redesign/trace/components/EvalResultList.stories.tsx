import type { Meta, StoryObj } from '@storybook/react'

import { openaiAgentsWithEvals } from '../sampleFixtures/openaiAgentsWithEvals'
import { FIXTURE_EVALS, FIXTURE_TREE, withWidth } from '../storyFixtures'
import { stepLabelsOf } from '../traceTreeLookups'
import { EvalResultList } from './EvalResultList'

const root = FIXTURE_TREE[0]
const generation = root.children[1]

const meta: Meta<typeof EvalResultList> = {
    title: 'Scenes-App/AI observability/Trace view/Eval results',
    component: EvalResultList,
    args: {
        results: FIXTURE_EVALS,
        failed: false,
        viewedNode: generation,
        stepLabels: stepLabelsOf(FIXTURE_TREE),
        onSelectNode: () => {},
    },
}
export default meta

type Story = StoryObj<typeof EvalResultList>

export const Results: Story = {}
export const WithTargets: Story = { args: { viewedNode: root } }
export const Narrow: Story = {
    args: { viewedNode: root },
    decorators: [withWidth(420)],
}
export const AgentEvals: Story = {
    args: {
        results: openaiAgentsWithEvals.evaluationResults,
        viewedNode: openaiAgentsWithEvals.tree[0],
        stepLabels: stepLabelsOf(openaiAgentsWithEvals.tree),
    },
}
export const Loading: Story = {
    args: { results: null },
    decorators: [withWidth(720)],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Empty: Story = { args: { results: [] } }
export const LoadError: Story = { args: { results: null, failed: true } }
