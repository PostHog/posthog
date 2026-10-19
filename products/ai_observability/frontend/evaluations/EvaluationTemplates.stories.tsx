import type { Meta, StoryObj } from '@storybook/react'

import { EvaluationTemplatesScene } from './EvaluationTemplates'

const meta: Meta<typeof EvaluationTemplatesScene> = {
    title: 'Scenes-App/LLM observability/Evaluation templates',
    component: EvaluationTemplatesScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof EvaluationTemplatesScene>

export const Default: Story = {}

export const Narrow: Story = {
    render: () => (
        <div className="max-w-[32rem]">
            <EvaluationTemplatesScene />
        </div>
    ),
}
