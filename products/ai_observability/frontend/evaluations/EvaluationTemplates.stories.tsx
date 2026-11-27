import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { EvaluationTemplatesScene } from './EvaluationTemplates'

const meta: Meta<typeof EvaluationTemplatesScene> = {
    title: 'Scenes-App/LLM observability/Evaluation templates',
    component: EvaluationTemplatesScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: [{ id: 'key-1', provider: 'openai', name: 'OpenAI', state: 'ok' }],
                },
            },
        }),
    ],
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

export const WithoutApiKey: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/environments/:team_id/llm_analytics/provider_keys/': { results: [] } },
        }),
    ],
}
