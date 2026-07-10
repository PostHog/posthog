import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { EVALUATION_SUMMARY_MAX_RUNS } from './constants'
import { evaluationReportLogic } from './evaluationReportLogic'
import { DEFAULT_HOG_SOURCE, DEFAULT_TRACE_HOG_SOURCE, llmEvaluationLogic } from './llmEvaluationLogic'
import { EvaluationConfig, EvaluationReport, EvaluationRun } from './types'

const mockProviderKeys: LLMProviderKey[] = [
    {
        id: 'key-1',
        provider: 'openai',
        name: 'Production Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-...1234',
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
    {
        id: 'key-2',
        provider: 'anthropic',
        name: 'Anthropic Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-ant-...5678',
        created_at: '2024-01-02T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
    {
        id: 'key-3',
        provider: 'openrouter',
        name: 'OpenRouter Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'sk-or-...9012',
        created_at: '2024-01-03T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
    {
        id: 'key-4',
        provider: 'fireworks',
        name: 'Fireworks Key',
        state: 'ok',
        error_message: null,
        api_key_masked: 'fw-...3456',
        created_at: '2024-01-04T00:00:00Z',
        created_by: null,
        last_used_at: null,
        azure_endpoint_display: null,
        api_version_display: null,
    },
]

const mockEvaluation: EvaluationConfig = {
    id: 'eval-123',
    name: 'Test Evaluation',
    description: 'A test evaluation',
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Is this response helpful?' },
    output_type: 'boolean',
    output_config: { allows_na: false },
    conditions: [{ id: 'cond-1', rollout_percentage: 50, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: {
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: 'key-1',
    },
    total_runs: 10,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

const mockEvaluationReport: EvaluationReport = {
    id: 'report-123',
    evaluation: 'eval-123',
    frequency: 'scheduled',
    rrule: 'FREQ=WEEKLY;BYDAY=FR',
    starts_at: '2024-01-01T00:00:00Z',
    timezone_name: 'UTC',
    next_delivery_date: '2024-01-05T00:00:00Z',
    delivery_targets: [{ type: 'email', value: 'alerts@example.com' }],
    max_sample_size: 200,
    enabled: true,
    deleted: false,
    last_delivered_at: null,
    report_prompt_guidance: 'Focus on regressions.',
    trigger_threshold: 500,
    cooldown_minutes: 180,
    daily_run_cap: 8,
    created_by: null,
    created_at: '2024-01-01T00:00:00Z',
}

const mockRuns: EvaluationRun[] = [
    {
        id: 'run-1',
        evaluation_id: 'eval-123',
        evaluation_name: 'Test Evaluation',
        generation_id: 'gen-1',
        trace_id: 'trace-1',
        timestamp: '2024-01-01T12:00:00Z',
        result: true,
        applicable: true,
        reasoning: 'The response was helpful',
        status: 'completed',
    },
    {
        id: 'run-2',
        evaluation_id: 'eval-123',
        evaluation_name: 'Test Evaluation',
        generation_id: 'gen-2',
        trace_id: 'trace-2',
        timestamp: '2024-01-01T13:00:00Z',
        result: false,
        applicable: true,
        reasoning: 'The response was not helpful',
        status: 'completed',
    },
    {
        id: 'run-3',
        evaluation_id: 'eval-123',
        evaluation_name: 'Test Evaluation',
        generation_id: 'gen-3',
        trace_id: 'trace-3',
        timestamp: '2024-01-01T14:00:00Z',
        result: null,
        applicable: false,
        reasoning: 'Not applicable',
        status: 'completed',
    },
]

const mockSentimentEvaluation: EvaluationConfig = {
    ...mockEvaluation,
    evaluation_type: 'sentiment',
    evaluation_config: { source: 'user_messages' },
    output_type: 'sentiment',
    output_config: {},
    model_configuration: null,
}

const mockSentimentRuns: EvaluationRun[] = [
    {
        id: 'run-negative',
        evaluation_id: 'eval-123',
        evaluation_name: 'Sentiment Evaluation',
        generation_id: 'gen-negative',
        trace_id: 'trace-negative',
        timestamp: '2024-01-01T12:00:00Z',
        evaluation_type: 'sentiment',
        result_type: 'sentiment',
        result: null,
        sentiment_label: 'negative',
        sentiment_score: -0.8,
        reasoning: 'The message was frustrated',
        status: 'completed',
    },
    {
        id: 'run-positive',
        evaluation_id: 'eval-123',
        evaluation_name: 'Sentiment Evaluation',
        generation_id: 'gen-positive',
        trace_id: 'trace-positive',
        timestamp: '2024-01-01T13:00:00Z',
        evaluation_type: 'sentiment',
        result_type: 'sentiment',
        result: null,
        sentiment_label: 'positive',
        sentiment_score: 0.7,
        reasoning: 'The message was happy',
        status: 'completed',
    },
    {
        id: 'run-neutral',
        evaluation_id: 'eval-123',
        evaluation_name: 'Sentiment Evaluation',
        generation_id: 'gen-neutral',
        trace_id: 'trace-neutral',
        timestamp: '2024-01-01T14:00:00Z',
        evaluation_type: 'sentiment',
        result_type: 'sentiment',
        result: null,
        sentiment_label: 'neutral',
        sentiment_score: 0.1,
        reasoning: 'The message was neutral',
        status: 'completed',
    },
    {
        id: 'run-positive-failed',
        evaluation_id: 'eval-123',
        evaluation_name: 'Sentiment Evaluation',
        generation_id: 'gen-positive-failed',
        trace_id: 'trace-positive-failed',
        timestamp: '2024-01-01T15:00:00Z',
        evaluation_type: 'sentiment',
        result_type: 'sentiment',
        result: null,
        sentiment_label: 'positive',
        sentiment_score: 0.5,
        reasoning: 'This run did not complete',
        status: 'failed',
    },
]

describe('llmEvaluationLogic', () => {
    let logic: ReturnType<typeof llmEvaluationLogic.build>
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
                '/api/projects/:teamId/evaluations/:id/': mockEvaluation,
                '/api/environments/:teamId/llm_analytics/models/': {
                    models: [
                        { id: 'gpt-5-mini', posthog_available: true },
                        { id: 'gpt-5', posthog_available: false },
                    ],
                },
            },
        })
        initKeaTests()
        keysLogic = llmProviderKeysLogic()
        keysLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        keysLogic?.unmount()
    })

    describe('reducers', () => {
        beforeEach(() => {
            logic = llmEvaluationLogic({ evaluationId: 'new' })
            logic.mount()
        })

        it('setEvaluationName updates evaluation name', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationName('New Name')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ name: 'New Name' }),
                hasUnsavedChanges: true,
            })
        })

        it('setEvaluationPrompt updates evaluation prompt', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationPrompt('New prompt')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_config: { prompt: 'New prompt' },
                }),
            })
        })

        it('setAllowsNA updates output config', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setAllowsNA(true)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    output_config: { allows_na: true },
                }),
            })
        })

        it('setTriggerConditions updates conditions', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            const newConditions = [{ id: 'new-cond', rollout_percentage: 100, properties: [] }]
            logic.actions.setTriggerConditions(newConditions)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ conditions: newConditions }),
            })
        })

        it('initializes new evaluations with 100% sampling', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    conditions: [expect.objectContaining({ rollout_percentage: 100 })],
                }),
            })
        })

        it('setModelConfiguration updates model config', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            const newConfig = { provider: 'anthropic' as const, model: 'claude-3-5-haiku', provider_key_id: 'key-2' }
            logic.actions.setModelConfiguration(newConfig)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ model_configuration: newConfig }),
            })
        })

        it('hasUnsavedChanges resets on save success', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationName('Changed Name')

            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: true })

            logic.actions.saveEvaluationSuccess(mockEvaluation)

            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })
        })

        it('seeds the trace Hog default when switching to hog with a trace target', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationTarget('trace')
            logic.actions.setEvaluationType('hog')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_config: { source: DEFAULT_TRACE_HOG_SOURCE },
                }),
            })
        })

        it('swaps the untouched Hog default when the target changes', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ evaluation_config: { source: DEFAULT_HOG_SOURCE } }),
            })

            logic.actions.setEvaluationTarget('trace')
            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({ evaluation_config: { source: DEFAULT_TRACE_HOG_SOURCE } }),
            })
        })

        it('does not clobber an edited Hog source when the target changes', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            logic.actions.setHogSource('return length(events) > 5')
            logic.actions.setEvaluationTarget('trace')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_config: expect.objectContaining({ source: 'return length(events) > 5' }),
                }),
            })
        })
    })

    describe('selectors', () => {
        describe('formValid', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()
            })

            it('returns false when evaluation is null', async () => {
                expect(logic.values.formValid).toBe(false)
            })

            it('returns false when name is empty', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns false when prompt is empty', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns false when an LLM judge has no selected model', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns false when no conditions have rollout > 0', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 0, properties: [] }])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns false when conditions array is empty', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setTriggerConditions([])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it.each([
                ['rollout_percentage of 0', 0],
                ['rollout_percentage above 100', 150],
            ])('returns false when %s', async (_label, percentage) => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: percentage, properties: [] }])

                await expectLogic(logic).toMatchValues({ formValid: false })
            })

            it('returns true when all fields valid', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])
                logic.actions.setModelConfiguration({
                    provider: 'openai',
                    model: 'gpt-5-mini',
                    provider_key_id: 'key-1',
                })

                await expectLogic(logic).toMatchValues({ formValid: true })
            })

            // A loaded evaluation whose stored shape doesn't match its type (e.g. an llm_judge
            // record with no prompt) used to crash formValid with a TypeError on render.
            it.each([
                ['missing name', { ...mockEvaluation, name: undefined }],
                ['missing conditions', { ...mockEvaluation, conditions: undefined }],
                ['missing evaluation_config', { ...mockEvaluation, evaluation_config: undefined }],
                ['llm_judge missing prompt', { ...mockEvaluation, evaluation_config: {} }],
                ['hog missing source', { ...mockEvaluation, evaluation_type: 'hog' as const, evaluation_config: {} }],
            ])('returns false without throwing when %s', async (_label, malformed) => {
                logic.actions.loadEvaluationSuccess(malformed as unknown as EvaluationConfig)

                await expectLogic(logic).toMatchValues({ formValid: false })
            })
        })

        describe('modelSelectionRequired', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()
            })

            it('allows existing legacy evaluations without a model configuration to remain editable', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.loadEvaluationSuccess({ ...mockEvaluation, model_configuration: null })

                await expectLogic(logic).toMatchValues({ modelSelectionRequired: false, formValid: true })
            })

            it('requires an existing configured evaluation to keep a selected model', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.setModelConfiguration(null)

                await expectLogic(logic).toMatchValues({ modelSelectionRequired: true, formValid: false })
            })

            it('requires a model when converting an existing Hog evaluation to an LLM judge', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.loadEvaluationSuccess({
                    ...mockEvaluation,
                    evaluation_type: 'hog',
                    evaluation_config: { source: DEFAULT_HOG_SOURCE },
                    model_configuration: null,
                })

                logic.actions.setEvaluationType('llm_judge')

                await expectLogic(logic).toMatchValues({ modelSelectionRequired: true, formValid: false })
            })
        })

        describe('evaluationProviderKeyIssue', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()
            })

            it.each([
                ['invalid' as const, 'Authentication failed'],
                ['error' as const, 'Quota exceeded'],
            ])('returns the provider key when state is %s', async (state, errorMessage) => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                keysLogic.actions.loadProviderKeysSuccess(
                    mockProviderKeys.map((key) =>
                        key.id === 'key-1' ? { ...key, state, error_message: errorMessage } : key
                    )
                )

                await expectLogic(logic).toMatchValues({
                    evaluationProviderKeyIssue: expect.objectContaining({
                        id: 'key-1',
                        state,
                        error_message: errorMessage,
                    }),
                })
            })

            it('returns null when evaluation uses the PostHog default key', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.loadEvaluationSuccess({
                    ...mockEvaluation,
                    model_configuration: null,
                })

                await expectLogic(logic).toMatchValues({
                    evaluationProviderKeyIssue: null,
                })
            })

            it('returns null when provider key state is healthy', async () => {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    evaluationProviderKeyIssue: null,
                })
            })
        })

        describe('runsSummary', () => {
            beforeEach(() => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()
            })

            it('returns null when no runs', async () => {
                expect(logic.values.runsSummary).toBeNull()
            })

            it('calculates summary correctly', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)

                await expectLogic(logic).toMatchValues({
                    runsSummary: {
                        total: 3,
                        successful: 1,
                        failed: 1,
                        errors: 0,
                        successRate: 50,
                        applicabilityRate: 67,
                    },
                })
            })
        })
    })

    describe('async flows', () => {
        describe('loadEvaluation', () => {
            it('initializes new evaluation with default values', async () => {
                // Pin the team to a non-terminal state before mounting so the draft's enabled
                // default doesn't depend on config-fetch timing.
                keysLogic.actions.loadEvaluationConfigSuccess({
                    trial_eval_limit: 100,
                    trial_evals_used: 50,
                    trial_evals_remaining: 50,
                    trial_grandfathered: true,
                    trial_deprecation_date: '2026-07-17T00:00:00Z',
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                })
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    isNewEvaluation: true,
                    evaluation: expect.objectContaining({
                        id: '',
                        name: '',
                        enabled: true,
                        evaluation_type: 'llm_judge',
                        output_type: 'boolean',
                    }),
                })
            })

            it('initializes new evaluation disabled for terminal teams that require a provider key', async () => {
                keysLogic.actions.loadEvaluationConfigSuccess({
                    trial_eval_limit: 100,
                    trial_evals_used: 100,
                    trial_evals_remaining: 0,
                    trial_grandfathered: false,
                    trial_deprecation_date: '2026-07-17T00:00:00Z',
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                })
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    isNewEvaluation: true,
                    evaluation: expect.objectContaining({ enabled: false }),
                })
            })

            it('disables an enabled new draft when a late config load says the team requires a key', async () => {
                // The draft's enabled default is read before the config fetch resolves — the
                // listener must correct it when the config arrives late.
                keysLogic.actions.loadEvaluationConfigSuccess({
                    trial_eval_limit: 100,
                    trial_evals_used: 50,
                    trial_evals_remaining: 50,
                    trial_grandfathered: true,
                    trial_deprecation_date: '2026-07-17T00:00:00Z',
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                })
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({ enabled: true }),
                })

                keysLogic.actions.loadEvaluationConfigSuccess({
                    trial_eval_limit: 100,
                    trial_evals_used: 100,
                    trial_evals_remaining: 0,
                    trial_grandfathered: false,
                    trial_deprecation_date: '2026-07-17T00:00:00Z',
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                })

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({ enabled: false }),
                })
            })

            it('loads existing evaluation', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    isNewEvaluation: false,
                    evaluation: expect.objectContaining({
                        id: 'eval-123',
                        name: 'Test Evaluation',
                    }),
                })
            })

            it('applies template when provided', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'new', templateKey: 'factuality' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({
                        name: expect.any(String),
                        evaluation_config: expect.objectContaining({
                            prompt: expect.any(String),
                        }),
                    }),
                })
            })
        })

        describe('resetEvaluation', () => {
            it('resets new evaluation to defaults', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'new' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.setEvaluationName('Changed Name')
                logic.actions.resetEvaluation()

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({
                        name: '',
                        conditions: [expect.objectContaining({ rollout_percentage: 100 })],
                    }),
                    hasUnsavedChanges: false,
                })
            })

            it('resets existing evaluation to original', async () => {
                logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

                logic.actions.setEvaluationName('Changed Name')
                logic.actions.resetEvaluation()

                await expectLogic(logic).toMatchValues({
                    evaluation: expect.objectContaining({ name: 'Test Evaluation' }),
                    hasUnsavedChanges: false,
                })
            })
        })
    })

    describe('evaluation summary', () => {
        beforeEach(() => {
            logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
            logic.mount()
        })

        describe('evaluationSummaryFilter', () => {
            it('defaults to all', async () => {
                expect(logic.values.evaluationSummaryFilter).toBe('all')
            })

            it('updates when setEvaluationSummaryFilter is called', async () => {
                logic.actions.setEvaluationSummaryFilter('pass', 'all')

                await expectLogic(logic).toMatchValues({
                    evaluationSummaryFilter: 'pass',
                })
            })

            it('clears evaluationSummary when filter changes', async () => {
                // Simulate having a summary
                logic.actions.generateEvaluationSummarySuccess({
                    overall_assessment: 'Test',
                    pass_patterns: [],
                    fail_patterns: [],
                    na_patterns: [],
                    recommendations: [],
                    statistics: { total_analyzed: 10, pass_count: 5, fail_count: 3, na_count: 2 },
                })

                await expectLogic(logic).toMatchValues({
                    evaluationSummary: expect.objectContaining({ overall_assessment: 'Test' }),
                })

                logic.actions.setEvaluationSummaryFilter('fail', 'all')

                await expectLogic(logic).toMatchValues({
                    evaluationSummary: null,
                })
            })
        })

        describe('sentiment evaluation filters', () => {
            it('defaults to all for boolean evaluations', async () => {
                expect(logic.values.evaluationSummaryFilter).toBe('all')
            })

            it('defaults to negative for sentiment evaluations', async () => {
                logic.actions.loadEvaluationSuccess(mockSentimentEvaluation)

                await expectLogic(logic).toMatchValues({
                    evaluationSummaryFilter: 'negative',
                })
            })
        })

        describe('runsToSummarizeCount', () => {
            it('returns 0 when no runs', async () => {
                expect(logic.values.runsToSummarizeCount).toBe(0)
            })

            it('counts all completed runs when filter is all', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)

                await expectLogic(logic).toMatchValues({
                    runsToSummarizeCount: 3,
                })
            })

            it('counts only passing runs when filter is pass', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)
                logic.actions.setEvaluationSummaryFilter('pass', 'all')

                await expectLogic(logic).toMatchValues({
                    runsToSummarizeCount: 1,
                })
            })

            it('counts only failing runs when filter is fail', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)
                logic.actions.setEvaluationSummaryFilter('fail', 'all')

                await expectLogic(logic).toMatchValues({
                    runsToSummarizeCount: 1,
                })
            })

            it('counts only N/A runs when filter is na', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)
                logic.actions.setEvaluationSummaryFilter('na', 'all')

                await expectLogic(logic).toMatchValues({
                    runsToSummarizeCount: 1,
                })
            })

            it(`caps count at ${EVALUATION_SUMMARY_MAX_RUNS}`, async () => {
                const manyRuns = Array.from({ length: EVALUATION_SUMMARY_MAX_RUNS + 50 }, (_, i) => ({
                    ...mockRuns[0],
                    id: `run-${i}`,
                    generation_id: `gen-${i}`,
                }))
                logic.actions.loadEvaluationRunsSuccess(manyRuns)

                await expectLogic(logic).toMatchValues({
                    runsToSummarizeCount: EVALUATION_SUMMARY_MAX_RUNS,
                })
            })
        })

        describe('summaryExpanded', () => {
            it('defaults to true', async () => {
                expect(logic.values.summaryExpanded).toBe(true)
            })

            it('toggles on toggleSummaryExpanded', async () => {
                logic.actions.toggleSummaryExpanded()

                await expectLogic(logic).toMatchValues({
                    summaryExpanded: false,
                })

                logic.actions.toggleSummaryExpanded()

                await expectLogic(logic).toMatchValues({
                    summaryExpanded: true,
                })
            })

            it('expands on generateEvaluationSummarySuccess', async () => {
                logic.actions.toggleSummaryExpanded() // collapse

                await expectLogic(logic).toMatchValues({ summaryExpanded: false })

                logic.actions.generateEvaluationSummarySuccess({
                    overall_assessment: 'Test',
                    pass_patterns: [],
                    fail_patterns: [],
                    na_patterns: [],
                    recommendations: [],
                    statistics: { total_analyzed: 10, pass_count: 5, fail_count: 3, na_count: 2 },
                })

                await expectLogic(logic).toMatchValues({
                    summaryExpanded: true,
                })
            })
        })

        describe('filteredEvaluationRuns', () => {
            it('returns all runs when filter is all', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: mockRuns,
                })
            })

            it('returns only passing runs when filter is pass', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)
                logic.actions.setEvaluationSummaryFilter('pass', 'all')

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: [expect.objectContaining({ id: 'run-1', result: true })],
                })
            })

            it('returns only failing runs when filter is fail', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)
                logic.actions.setEvaluationSummaryFilter('fail', 'all')

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: [expect.objectContaining({ id: 'run-2', result: false })],
                })
            })

            it('returns only N/A runs when filter is na', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)
                logic.actions.setEvaluationSummaryFilter('na', 'all')

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: [expect.objectContaining({ id: 'run-3', result: null })],
                })
            })

            it('excludes non-completed runs when filter is not all', async () => {
                const runsWithFailed: EvaluationRun[] = [
                    ...mockRuns,
                    {
                        id: 'run-4',
                        evaluation_id: 'eval-123',
                        evaluation_name: 'Test Evaluation',
                        generation_id: 'gen-4',
                        trace_id: 'trace-4',
                        timestamp: '2024-01-01T15:00:00Z',
                        result: true,
                        reasoning: 'Good',
                        status: 'failed',
                    },
                ]
                logic.actions.loadEvaluationRunsSuccess(runsWithFailed)
                logic.actions.setEvaluationSummaryFilter('pass', 'all')

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: [expect.objectContaining({ id: 'run-1' })],
                })
            })

            it('returns only negative sentiment runs by default for sentiment evaluations', async () => {
                logic.actions.loadEvaluationSuccess(mockSentimentEvaluation)
                logic.actions.loadEvaluationRunsSuccess(mockSentimentRuns)

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: [expect.objectContaining({ id: 'run-negative' })],
                })
            })

            it('returns only completed sentiment runs matching the selected filter', async () => {
                logic.actions.loadEvaluationSuccess(mockSentimentEvaluation)
                logic.actions.loadEvaluationRunsSuccess(mockSentimentRuns)
                logic.actions.setEvaluationSummaryFilter('positive', 'negative')

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: [expect.objectContaining({ id: 'run-positive' })],
                })
            })

            it('returns all sentiment runs when the all filter is selected', async () => {
                logic.actions.loadEvaluationSuccess(mockSentimentEvaluation)
                logic.actions.loadEvaluationRunsSuccess(mockSentimentRuns)
                logic.actions.setEvaluationSummaryFilter('all', 'negative')

                await expectLogic(logic).toMatchValues({
                    filteredEvaluationRuns: mockSentimentRuns,
                })
            })
        })

        describe('runsLookup', () => {
            it('creates lookup by generation_id', async () => {
                logic.actions.loadEvaluationRunsSuccess(mockRuns)

                await expectLogic(logic).toMatchValues({
                    runsLookup: {
                        'gen-1': expect.objectContaining({ id: 'run-1' }),
                        'gen-2': expect.objectContaining({ id: 'run-2' }),
                        'gen-3': expect.objectContaining({ id: 'run-3' }),
                    },
                })
            })
        })
    })

    describe('hog evaluation type', () => {
        beforeEach(() => {
            logic = llmEvaluationLogic({ evaluationId: 'new' })
            logic.mount()
        })

        it('setEvaluationType switches to hog config shape', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_type: 'hog',
                    evaluation_config: { source: DEFAULT_HOG_SOURCE },
                    model_configuration: null,
                }),
            })
        })

        it('setEvaluationType switches back to llm_judge config shape', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            logic.actions.setEvaluationType('llm_judge')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_type: 'llm_judge',
                    evaluation_config: { prompt: '' },
                }),
            })
        })

        it('setEvaluationType switches to sentiment config shape', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('sentiment')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_type: 'sentiment',
                    evaluation_config: { source: 'user_messages' },
                    output_type: 'sentiment',
                    output_config: {},
                    model_configuration: null,
                    conditions: [expect.objectContaining({ rollout_percentage: 100 })],
                }),
            })
        })

        it('switching to sentiment resets a trace target back to generation', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationTarget('trace')
            logic.actions.setEvaluationType('sentiment')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_type: 'sentiment',
                    target: 'generation',
                    target_config: {},
                }),
            })
        })

        it('initializes new evaluations as sentiment when requested', async () => {
            logic.unmount()
            logic = llmEvaluationLogic({ evaluationId: 'new', evaluationType: 'sentiment' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_type: 'sentiment',
                    evaluation_config: { source: 'user_messages' },
                    output_type: 'sentiment',
                    output_config: {},
                    model_configuration: null,
                }),
            })
        })

        it('switching to sentiment moves away from reports tab', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setActiveTab('reports')
            logic.actions.setEvaluationType('sentiment')

            await expectLogic(logic).toMatchValues({
                activeTab: 'configuration',
            })
        })

        it('setHogSource updates source in hog config', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            logic.actions.setHogSource('return true')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    evaluation_config: { source: 'return true' },
                }),
            })
        })

        it('formValid checks source for hog type', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            logic.actions.setEvaluationName('Valid Name')
            logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])

            // Default source is non-empty -> valid
            await expectLogic(logic).toMatchValues({ formValid: true })

            logic.actions.setHogSource('')

            // Empty source -> invalid
            await expectLogic(logic).toMatchValues({ formValid: false })

            logic.actions.setHogSource('return true')

            // Non-empty source -> valid again
            await expectLogic(logic).toMatchValues({ formValid: true })
        })

        it('formValid rejects whitespace-only source', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            logic.actions.setEvaluationName('Valid Name')
            logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])
            logic.actions.setHogSource('   ')

            await expectLogic(logic).toMatchValues({ formValid: false })
        })

        it('formValid does not require prompt or code for sentiment type', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('sentiment')
            logic.actions.setEvaluationName('Valid Name')
            logic.actions.setTriggerConditions([{ id: 'c1', rollout_percentage: 50, properties: [] }])

            await expectLogic(logic).toMatchValues({ formValid: true })
        })

        it('setAllowsNA does not mutate sentiment output config', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('sentiment')
            logic.actions.setAllowsNA(true)

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    output_type: 'sentiment',
                    output_config: {},
                }),
            })
        })

        it('setEvaluationType marks unsaved changes', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')

            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: true })
        })

        it('setHogSource marks unsaved changes', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.setEvaluationType('hog')
            // Clear the flag
            logic.actions.saveEvaluationSuccess({
                ...mockEvaluation,
                evaluation_type: 'hog',
                evaluation_config: { source: DEFAULT_HOG_SOURCE },
            } as any)

            logic.actions.setHogSource('return true')

            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: true })
        })
    })

    describe('selectModelFromPicker', () => {
        beforeEach(() => {
            logic = llmEvaluationLogic({ evaluationId: 'new' })
            logic.mount()
        })

        it('sets model configuration from BYOK provider key', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
            await expectLogic(keysLogic).toDispatchActions(['loadProviderKeysSuccess'])

            logic.actions.selectModelFromPicker('gpt-5', 'key-1')

            await expectLogic(logic).toMatchValues({
                selectedModel: 'gpt-5',
                evaluation: expect.objectContaining({
                    model_configuration: {
                        provider: 'openai',
                        model: 'gpt-5',
                        provider_key_id: 'key-1',
                    },
                }),
            })
        })

        it('sets model configuration from trial provider key', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.selectModelFromPicker('gpt-5', 'trial:openai')

            await expectLogic(logic).toMatchValues({
                selectedModel: 'gpt-5',
                evaluation: expect.objectContaining({
                    model_configuration: {
                        provider: 'openai',
                        model: 'gpt-5',
                        provider_key_id: null,
                    },
                }),
            })
        })

        it('ignores empty modelId', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])

            logic.actions.selectModelFromPicker('', 'key-1')

            await expectLogic(logic).toMatchValues({
                evaluation: expect.objectContaining({
                    model_configuration: null,
                }),
            })
        })
    })

    describe('saveEvaluation report persistence', () => {
        it('does not create an evaluation when the report threshold is invalid', async () => {
            let evaluationCreateCount = 0
            useMocks({
                post: {
                    '/api/projects/:teamId/evaluations/': () => {
                        evaluationCreateCount += 1
                        return mockEvaluation
                    },
                },
            })

            logic = llmEvaluationLogic({ evaluationId: 'new' })
            const reportLogic = evaluationReportLogic({ evaluationId: 'new' })
            logic.mount()
            reportLogic.mount()

            try {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                logic.actions.setEvaluationName('Valid Name')
                logic.actions.setEvaluationPrompt('Valid prompt')
                logic.actions.setModelConfiguration({
                    provider: 'openai',
                    model: 'gpt-5-mini',
                    provider_key_id: 'key-1',
                })
                reportLogic.actions.setDraftTriggerThreshold(67)

                expect(reportLogic.values.configErrors.triggerThreshold).toBe(
                    'Evaluation count threshold must be a whole number between 100 and 10,000.'
                )

                logic.actions.saveEvaluation()

                await expectLogic(logic)
                    .toDispatchActions(['saveEvaluationFailure'])
                    .toMatchValues({ evaluationFormSubmitting: false })
                expect(evaluationCreateCount).toBe(0)
            } finally {
                reportLogic.unmount()
            }
        })

        it('does not overwrite a saved report with defaults before the report load finishes', async () => {
            let reportWriteCount = 0
            let reportListRequestCount = 0
            let resolveInitialReports: (value: { results: EvaluationReport[] }) => void = () => {}
            const initialReportsPromise = new Promise<{ results: EvaluationReport[] }>((resolve) => {
                resolveInitialReports = resolve
            })
            let resolveNavigation: () => void = () => {}
            const navigationPromise = new Promise<void>((resolve) => {
                resolveNavigation = resolve
            })
            const pushSpy = jest.spyOn(router.actions, 'push').mockImplementation(() => {
                resolveNavigation()
            })

            useMocks({
                get: {
                    '/api/projects/:teamId/llm_analytics/evaluation_reports/': () => {
                        reportListRequestCount += 1
                        return reportListRequestCount === 1
                            ? initialReportsPromise
                            : { results: [mockEvaluationReport] }
                    },
                },
                patch: {
                    '/api/projects/:teamId/evaluations/:id/': () => mockEvaluation,
                    '/api/projects/:teamId/llm_analytics/evaluation_reports/:id/': () => {
                        reportWriteCount += 1
                        return mockEvaluationReport
                    },
                },
                post: {
                    '/api/projects/:teamId/llm_analytics/evaluation_reports/': () => {
                        reportWriteCount += 1
                        return mockEvaluationReport
                    },
                },
            })

            logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
            const reportLogic = evaluationReportLogic({ evaluationId: 'eval-123' })
            logic.mount()
            reportLogic.mount()

            try {
                await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
                expect(reportLogic.values.reportsLoading).toBe(true)
                expect(reportLogic.values.activeReport).toBeNull()

                logic.actions.setEvaluationName('Renamed evaluation')
                logic.actions.saveEvaluation()

                await navigationPromise

                expect(reportListRequestCount).toBe(1)
                expect(reportWriteCount).toBe(0)
                resolveInitialReports({ results: [mockEvaluationReport] })
                await expectLogic(reportLogic).toFinishAllListeners()
            } finally {
                pushSpy.mockRestore()
                reportLogic.unmount()
            }
        })
    })

    describe('saveEvaluation failure handling', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/environments/:teamId/llm_analytics/provider_keys/': { results: mockProviderKeys },
                    '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                        trial_eval_limit: 100,
                        trial_evals_used: 100,
                        trial_evals_remaining: 0,
                        trial_grandfathered: false,
                        trial_deprecation_date: '2026-07-15T00:00:00Z',
                        active_provider_key: null,
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                    },
                    '/api/projects/:teamId/evaluations/:id/': mockEvaluation,
                },
                patch: {
                    '/api/projects/:teamId/evaluations/:id/': () => [
                        400,
                        {
                            enabled: ['Trial evaluation limit reached. Add a provider API key to re-enable.'],
                        },
                    ],
                },
            })

            logic = llmEvaluationLogic({ evaluationId: 'eval-123' })
            logic.mount()
        })

        it('dispatches saveEvaluationFailure and resets submitting state on 400', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationSuccess'])
            logic.actions.setEvaluationName('Renamed')

            logic.actions.saveEvaluation()

            await expectLogic(logic)
                .toDispatchActions(['saveEvaluation', 'saveEvaluationFailure'])
                .toMatchValues({ evaluationFormSubmitting: false })
        })
    })
})
