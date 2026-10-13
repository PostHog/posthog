import type { Meta, StoryObj } from '@storybook/react'

import { openaiAgentsEvals } from '../sampleFixtures/openaiAgentsWithEvals'
import { FIXTURE_EVALS, FIXTURE_TRACE_EVALS, withWidth } from '../storyFixtures'
import { EvalResultList } from './EvalResultList'

const meta: Meta<typeof EvalResultList> = {
    title: 'Scenes-App/AI observability/Trace view/Eval results',
    component: EvalResultList,
    args: { onSelectNode: () => {} },
}
export default meta

type Story = StoryObj<typeof EvalResultList>

export const Results: Story = { args: { evals: { status: 'ready', results: FIXTURE_EVALS } } }
export const WithTargets: Story = { args: { evals: { status: 'ready', results: FIXTURE_TRACE_EVALS } } }
export const Narrow: Story = {
    args: { evals: { status: 'ready', results: FIXTURE_TRACE_EVALS } },
    decorators: [withWidth(420)],
}
export const AgentEvals: Story = { args: { evals: { status: 'ready', results: openaiAgentsEvals } } }
export const Loading: Story = {
    args: { evals: { status: 'loading' } },
    decorators: [withWidth(720)],
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const Empty: Story = { args: { evals: { status: 'ready', results: [] } } }
export const LoadError: Story = {
    args: { evals: { status: 'error', errorMessage: 'Evaluation results could not be loaded. Try again later.' } },
}
