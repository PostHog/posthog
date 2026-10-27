import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import type { JudgeMethod } from '../types'
import { EvaluationModelPicker } from './EvaluationModelPicker'

const meta: Meta<{ method?: JudgeMethod; narrow?: boolean; empty?: boolean; nativeOpenAI?: boolean }> = {
    title: 'Scenes-App/LLM observability/EvaluationModelPicker',
    component: EvaluationModelPicker,
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.LLM_ANALYTICS_SYSTEM_ONE_EVALUATIONS],
    },
    render: ({ method = 'llm', narrow = false, empty = false, nativeOpenAI = false }) => {
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
                    evaluation_config: { prompt: 'Does the response answer the question?', judge_method: method },
                    output_type: 'boolean',
                    output_config: {},
                    conditions: [],
                    target: 'generation',
                    target_config: {},
                    model_configuration: null,
                },
            },
        })
        return (
            <BindLogic logic={llmEvaluationLogic} props={{ evaluationId: 'example-evaluation' }}>
                <div className={narrow ? 'max-w-lg' : 'max-w-4xl'}>
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
export const FlagOff: Story = { parameters: { featureFlags: [] } }
export const NativeOpenAI: Story = { args: { method: 'decision', nativeOpenAI: true } }
export const NativeOpenAINarrow: Story = { args: { method: 'decision', nativeOpenAI: true, narrow: true } }
