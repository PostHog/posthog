import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { EvaluationsScene } from './EvaluationsScene'

const meta: Meta<typeof EvaluationsScene> = {
    title: 'Scenes-App/AI observability/Evaluations/Onboarding',
    component: EvaluationsScene,
    parameters: {
        pageUrl: urls.aiObservabilityEvaluations(),
        mockDate: '2026-10-01',
        featureFlags: [FEATURE_FLAGS.LLM_ANALYTICS_DATASETS, FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS],
        testOptions: { waitForSelector: '[data-attr="create-evaluation-button"]' },
    },
    decorators: [
        (Story, { parameters }) => (
            <div className={parameters.narrow ? 'w-[520px]' : 'w-[1200px]'}>
                <Story />
            </div>
        ),
        mswDecorator({
            get: {
                '/api/projects/:team/evaluations/': { count: 0, results: [], next: null, previous: null },
                '/api/projects/:team/evaluation_directories/': [],
                '/api/environments/:team/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:team/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    trial_evals_enabled: false,
                },
            },
        }),
    ],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('Score AI responses as they happen')
        sceneLogic.actions.setScene(Scene.AIObservabilityEvaluations, undefined, {
            params: {},
            searchParams: {},
            hashParams: {},
        })
        for (const label of ['Online evals', 'Offline evals', 'Scorers']) {
            if (!canvas.getByText(label).closest('a')?.getAttribute('href')) {
                throw new Error(`${label} must remain reachable before creating an online evaluation`)
            }
        }
    },
}

export default meta
type Story = StoryObj<typeof EvaluationsScene>

export const NoOnlineEvaluations: Story = {}

export const Narrow: Story = {
    parameters: { narrow: true },
}
