import type { Meta, StoryObj } from '@storybook/react'

import { EvaluationExplanation } from './EvaluationExplanation'

const meta: Meta<typeof EvaluationExplanation> = {
    title: 'Scenes-App/AI observability/Evaluation explanation',
    component: EvaluationExplanation,
}
export default meta

export const Reasoning: StoryObj<typeof EvaluationExplanation> = {
    args: { reasoning: 'The response answers the question and includes a polite greeting.' },
}

export const SystemOne: StoryObj<typeof EvaluationExplanation> = {
    args: { probability: 0.84 },
}

export const SystemOneZeroProbability: StoryObj<typeof EvaluationExplanation> = {
    args: { probability: 0 },
}
