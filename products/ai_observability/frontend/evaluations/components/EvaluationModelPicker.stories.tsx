import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { JudgeMethod, ReasoningLevel } from '../types'
import { EvaluationModelPicker } from './EvaluationModelPicker'

const meta: Meta<{
    method?: JudgeMethod
    narrow?: boolean
    empty?: boolean
    nativeOpenAI?: boolean
    reasoningLevel?: ReasoningLevel
}> = {
    title: 'Scenes-App/LLM observability/EvaluationModelPicker',
    component: EvaluationModelPicker,
    parameters: {
        layout: 'padded',
    },
    render: ({ method = 'llm', narrow = false, empty = false, nativeOpenAI = false, reasoningLevel }) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/llm_analytics/provider_keys/': {
                    results: [
                        nativeOpenAI
                            ? { id: 'example-openai-key', name: 'OpenAI', provider: 'openai', state: 'ok' }
                            : { id: 'example-openrouter-key', name: 'OpenRouter', provider: 'openrouter', state: 'ok' },
                    ],
                },
                '/api/environments/:team_id/llm_analytics/evaluation_config/': { active_provider_key: null },
                '/api/llm_proxy/models/': ({ request }) => [
                    200,
                    new URL(request.url).searchParams.has('provider_key_id')
                        ? nativeOpenAI
                            ? [
                                  {
                                      id: 'gpt-5-mini',
                                      name: 'gpt-5-mini',
                                      provider: 'OpenAI',
                                      supports_chat: true,
                                      supports_decisions: false,
                                      supports_reasoning: true,
                                  },
                                  {
                                      id: 'gpt-6-luna',
                                      name: 'gpt-6-luna',
                                      provider: 'OpenAI',
                                      supports_chat: true,
                                      supports_decisions: true,
                                  },
                              ]
                            : [
                                  {
                                      id: 'example/chat-model',
                                      name: 'example/chat-model',
                                      provider: 'OpenRouter',
                                      supports_chat: true,
                                      supports_decisions: false,
                                  },
                                  ...(!empty
                                      ? [
                                            {
                                                id: 'example/decision-model',
                                                name: 'example/decision-model',
                                                provider: 'OpenRouter',
                                                supports_chat: false,
                                                supports_decisions: true,
                                            },
                                            {
                                                id: 'example/dual-model',
                                                name: 'example/dual-model',
                                                provider: 'OpenRouter',
                                                supports_chat: true,
                                                supports_decisions: true,
                                            },
                                        ]
                                      : []),
                              ]
                        : [],
                ],
                '/api/projects/:team_id/evaluations/example-evaluation/': {
                    id: 'example-evaluation',
                    name: 'Response quality',
                    enabled: false,
                    evaluation_type: 'llm_judge',
                    evaluation_config: {
                        prompt: 'Does the response answer the question?',
                        judge_method: method,
                        reasoning_level: reasoningLevel,
                    },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [],
                    target: 'generation',
                    target_config: {},
                    model_configuration: reasoningLevel
                        ? { provider: 'openai', model: 'gpt-5-mini', provider_key_id: 'example-openai-key' }
                        : null,
                },
            },
        })
        return (
            <BindLogic logic={llmEvaluationLogic} props={{ evaluationId: 'example-evaluation' }}>
                <div className={narrow ? 'w-[32rem]' : 'max-w-4xl'}>
                    <EvaluationModelPicker />
                </div>
            </BindLogic>
        )
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const LLM: Story = { args: { method: 'llm' } }
export const Decision: Story = { args: { method: 'decision' } }
export const DecisionNarrow: Story = { args: { method: 'decision', narrow: true } }
export const NoDecisionModels: Story = { args: { method: 'decision', empty: true } }
export const NativeOpenAI: Story = { args: { method: 'decision', nativeOpenAI: true } }
export const NativeOpenAINarrow: Story = { args: { method: 'decision', nativeOpenAI: true, narrow: true } }
export const WithAttachments: Story = {
    args: { method: 'llm' },
    parameters: { featureFlags: [FEATURE_FLAGS.LLM_ANALYTICS_JUDGE_IMAGES], testOptions: { snapshotBrowsers: [] } },
}
export const ReasoningLevelNarrow: Story = {
    args: { method: 'llm', nativeOpenAI: true, narrow: true, reasoningLevel: 'medium' },
}
