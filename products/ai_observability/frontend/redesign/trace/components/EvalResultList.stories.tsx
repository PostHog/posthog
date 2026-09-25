import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_EVALS } from '../storyFixtures'
import { EvalResultList } from './EvalResultList'

const meta: Meta<typeof EvalResultList> = {
    title: 'Scenes-App/AI observability/Trace view/Eval results',
    component: EvalResultList,
}
export default meta

type Story = StoryObj<typeof EvalResultList>

export const Results: Story = { args: { evals: { status: 'ready', results: FIXTURE_EVALS } } }
export const Loading: Story = { args: { evals: { status: 'loading' } } }
export const Empty: Story = { args: { evals: { status: 'ready', results: [] } } }
export const LoadError: Story = {
    args: { evals: { status: 'error', errorMessage: 'Evaluation results could not be loaded. Try again later.' } },
}
