import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { HogEvaluation, LLMJudgeEvaluation, SentimentEvaluation } from './types'

const mockProviderKeys: LLMProviderKey[] = [
    {
        id: 'key-ok',
        provider: 'openai',
        name: 'OpenAI production',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-...1111',
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
    {
        id: 'key-invalid',
        provider: 'anthropic',
        name: 'Anthropic key',
        state: 'invalid',
        error_message: 'Invalid API key',
        api_key_masked: 'sk-ant-...2222',
        created_at: '2024-01-02T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
    {
        id: 'key-error',
        provider: 'openrouter',
        name: 'OpenRouter key',
        state: 'error',
        error_message: 'Quota exceeded',
        api_key_masked: 'sk-or-...3333',
        created_at: '2024-01-03T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
]

const evaluationWithKey = (id: string, providerKeyId: string | null): LLMJudgeEvaluation => ({
    id,
    name: `Evaluation ${id}`,
    description: '',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Prompt' },
    output_type: 'boolean',
    output_config: {},
    conditions: [{ id: `cond-${id}`, rollout_percentage: 100, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: providerKeyId
        ? {
              provider: 'openai',
              model: 'gpt-5-mini',
              provider_key_id: providerKeyId,
          }
        : null,
    total_runs: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
})

const hogEvaluation = (id: string): HogEvaluation => ({
    ...evaluationWithKey(id, null),
    evaluation_type: 'hog',
    evaluation_config: { source: 'return true' },
    model_configuration: null,
})

const sentimentEvaluation = (id: string): SentimentEvaluation => ({
    ...evaluationWithKey(id, null),
    evaluation_type: 'sentiment',
    evaluation_config: { source: 'user_messages' },
    output_type: 'sentiment',
    output_config: {},
    model_configuration: null,
})

describe('llmEvaluationsLogic', () => {
    let logic: ReturnType<typeof llmEvaluationsLogic.build>
    let keysLogic: ReturnType<typeof llmProviderKeysLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: mockProviderKeys },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    trial_eval_limit: 100,
                    trial_evals_used: 0,
                    trial_evals_remaining: 100,
                    trial_grandfathered: false,
                    trial_deprecation_date: '2026-07-15T00:00:00Z',
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/environments/:teamId/evaluations/': {
                    results: [
                        evaluationWithKey('eval-ok', 'key-ok'),
                        evaluationWithKey('eval-invalid', 'key-invalid'),
                        evaluationWithKey('eval-error', 'key-error'),
                        evaluationWithKey('eval-invalid-duplicate', 'key-invalid'),
                        evaluationWithKey('eval-default', null),
                    ],
                },
            },
        })

        initKeaTests()
        keysLogic = llmProviderKeysLogic()
        keysLogic.mount()

        logic = llmEvaluationsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        keysLogic?.unmount()
    })

    describe('unhealthyProviderKeysUsedByEvaluations', () => {
        it('allows Hog and sentiment evaluations when trial limit is reached', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_SENTIMENT], {
                [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_SENTIMENT]: true,
            })
            keysLogic.actions.loadEvaluationConfigSuccess({
                trial_eval_limit: 100,
                trial_evals_used: 100,
                trial_evals_remaining: 0,
                trial_grandfathered: false,
                trial_deprecation_date: '2026-07-15T00:00:00Z',
                active_provider_key: null,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })

            expect(logic.values.canEnableEvaluation(hogEvaluation('hog'))).toBe(true)
            expect(logic.values.canEnableEvaluation(sentimentEvaluation('sentiment'))).toBe(true)
            expect(logic.values.canEnableEvaluation(evaluationWithKey('llm-default', null))).toBe(false)
        })

        it('an active team key only unlocks null-config evaluations, never explicit keyless ones', async () => {
            // Runtime resolution uses the active key only for null configs — explicit keyless
            // configs never fall back to it, so they stay blocked.
            keysLogic.actions.loadEvaluationConfigSuccess({
                trial_eval_limit: 100,
                trial_evals_used: 100,
                trial_evals_remaining: 0,
                trial_grandfathered: false,
                trial_deprecation_date: '2026-07-17T00:00:00Z',
                active_provider_key: mockProviderKeys[0],
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })

            const explicitKeyless: LLMJudgeEvaluation = {
                ...evaluationWithKey('llm-explicit', null),
                model_configuration: { provider: 'openai', model: 'gpt-5-mini', provider_key_id: null },
            }
            expect(logic.values.canEnableEvaluation(explicitKeyless)).toBe(false)
            expect(logic.values.canEnableEvaluation(evaluationWithKey('llm-default', null))).toBe(true)
        })

        it('returns unhealthy keys used by evaluations without duplicates', async () => {
            logic.actions.loadEvaluations()
            keysLogic.actions.loadProviderKeys()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.unhealthyProviderKeysUsedByEvaluations).toEqual([
                expect.objectContaining({ id: 'key-invalid', state: 'invalid' }),
                expect.objectContaining({ id: 'key-error', state: 'error' }),
            ])
        })

        it('optimistic toggle keeps status in sync with enabled', async () => {
            const errored = evaluationWithKey('eval-errored', 'key-ok')
            errored.enabled = false
            errored.status = 'error'
            errored.status_reason = 'trial_limit_reached'
            logic.actions.loadEvaluationsSuccess([errored])

            logic.actions.toggleEvaluationEnabledSuccess('eval-errored')

            await expectLogic(logic).toMatchValues({
                evaluations: [
                    expect.objectContaining({
                        enabled: true,
                        status: 'active',
                        status_reason: null,
                        status_reason_detail: null,
                    }),
                ],
            })
        })

        it('dispatches toggleEvaluationEnabledFailure when the API rejects the toggle', async () => {
            useMocks({
                patch: {
                    '/api/environments/:teamId/evaluations/:id/': () => [
                        400,
                        {
                            enabled: ['Trial evaluation limit reached. Add a provider API key to re-enable.'],
                        },
                    ],
                },
            })

            logic.actions.loadEvaluationsSuccess([evaluationWithKey('eval-default', null)])

            logic.actions.toggleEvaluationEnabled('eval-default')

            await expectLogic(logic).toDispatchActions(['toggleEvaluationEnabled', 'toggleEvaluationEnabledFailure'])
        })

        it('returns an empty array when all used keys are healthy', async () => {
            logic.actions.loadEvaluationsSuccess([
                evaluationWithKey('eval-ok-1', 'key-ok'),
                evaluationWithKey('eval-default', null),
            ])
            keysLogic.actions.loadProviderKeysSuccess([
                {
                    ...mockProviderKeys[0],
                    state: 'ok',
                    error_message: null,
                },
            ])

            await expectLogic(logic).toMatchValues({
                unhealthyProviderKeysUsedByEvaluations: [],
            })
        })
    })
})
