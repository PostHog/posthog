import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'
import preflight from '~/mocks/fixtures/_preflight.json'

import type { DecideRequestApi } from 'products/ml_inference/frontend/generated/api.schemas'

import { NavTabApps } from './NavTabApps'

const meta: Meta<typeof NavTabApps> = {
    title: 'Layout/Apps/Search',
    component: NavTabApps,
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.ML_INFERENCE_DECISIONS],
    },
    decorators: [
        mswDecorator({
            get: { '_preflight/': { ...preflight, is_debug: false } },
            post: {
                'api/projects/:team_id/ml_inference/decisions/decide/': async ({ request }) => {
                    const body = (await request.json()) as DecideRequestApi
                    return [
                        200,
                        {
                            model: 'jev-1.13.0',
                            input_tokens: 100,
                            latency_ms: 150,
                            answers: Object.fromEntries(
                                Object.entries(body.questions).map(([id, question]) => [
                                    id,
                                    {
                                        type: 'noul',
                                        probability: question.instructions.includes('"name":"Session replay"')
                                            ? 0.95
                                            : question.instructions.includes('"name":"Error tracking"')
                                              ? 0.7
                                              : 0.1,
                                        choice: null,
                                        score: null,
                                        confidence: null,
                                        probabilities: null,
                                    },
                                ])
                            ),
                        },
                    ]
                },
            },
        }),
    ],
    render: () => (
        <div className="w-64 h-screen border-r">
            <NavTabApps />
        </div>
    ),
}

export default meta
type Story = StoryObj<typeof NavTabApps>

export const Default: Story = {}
export const Narrow: Story = {
    render: () => (
        <div className="w-52 h-screen border-r">
            <NavTabApps />
        </div>
    ),
}
export const Dark: Story = { globals: { theme: 'dark' } }
export const NameFilter: Story = { parameters: { featureFlags: [] } }
