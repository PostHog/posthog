import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import { llmEvaluationsLogic, waitForEvaluationsSettled } from './llmEvaluationsLogic'
import {
    EvaluationConfig,
    EvaluationOutputConfig,
    HogEvaluation,
    LLMJudgeEvaluation,
    SentimentEvaluation,
} from './types'

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

const evaluationWithOutputConfig = (id: string, outputConfig: EvaluationOutputConfig): EvaluationConfig =>
    ({
        id,
        name: `Evaluation ${id}`,
        description: '',
        directory_id: null,
        enabled: true,
        status: 'active',
        status_reason: null,
        status_reason_detail: null,
        evaluation_type: 'llm_judge',
        evaluation_config: { prompt: 'Prompt' },
        output_type: 'boolean',
        output_config: outputConfig,
        conditions: [],
        target: 'generation',
        target_config: {},
        model_configuration: null,
        total_runs: 0,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
    }) as EvaluationConfig

const evaluationWithKey = (
    id: string,
    providerKeyId: string | null,
    directoryId: string | null = null
): LLMJudgeEvaluation => ({
    id,
    name: `Evaluation ${id}`,
    description: '',
    directory_id: directoryId,
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
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/': {
                    results: [
                        evaluationWithKey('eval-ok', 'key-ok'),
                        evaluationWithKey('eval-invalid', 'key-invalid'),
                        evaluationWithKey('eval-error', 'key-error'),
                        evaluationWithKey('eval-invalid-duplicate', 'key-invalid'),
                        evaluationWithKey('eval-default', null),
                    ],
                },
                '/api/projects/:teamId/evaluation_directories/': [
                    {
                        id: 'directory-a',
                        name: 'Directory A',
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                        created_by: null,
                        evaluation_count: 1,
                    },
                ],
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
        it('allows Hog and sentiment evaluations when a provider key is required', async () => {
            // Team with no active key → requiresProviderKey.
            keysLogic.actions.loadEvaluationConfigSuccess({
                active_provider_key: null,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })

            expect(logic.values.canEnableEvaluation(hogEvaluation('hog'))).toBe(true)
            expect(logic.values.canEnableEvaluation(sentimentEvaluation('sentiment'))).toBe(true)
            expect(logic.values.canEnableEvaluation(evaluationWithKey('llm-default', null))).toBe(false)
        })

        it('an active team key unlocks keyless llm_judge evaluations', async () => {
            keysLogic.actions.loadEvaluationConfigSuccess({
                active_provider_key: mockProviderKeys[0],
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })

            expect(logic.values.canEnableEvaluation(evaluationWithKey('llm-default', null))).toBe(true)
        })

        it('the active key must be healthy and match an explicit keyless config provider', async () => {
            const explicitKeyless: LLMJudgeEvaluation = {
                ...evaluationWithKey('llm-explicit', null),
                model_configuration: { provider: 'openai', model: 'gpt-5-mini', provider_key_id: null },
            }

            // Unhealthy active key resolves nothing.
            keysLogic.actions.loadEvaluationConfigSuccess({
                active_provider_key: mockProviderKeys[1],
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })
            expect(logic.values.canEnableEvaluation(evaluationWithKey('llm-default', null))).toBe(false)

            // Healthy, but for a different provider than the explicit config.
            keysLogic.actions.loadEvaluationConfigSuccess({
                active_provider_key: { ...mockProviderKeys[1], state: 'ok' },
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })
            expect(logic.values.canEnableEvaluation(explicitKeyless)).toBe(false)

            // Healthy and matching.
            keysLogic.actions.loadEvaluationConfigSuccess({
                active_provider_key: mockProviderKeys[0],
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            })
            expect(logic.values.canEnableEvaluation(explicitKeyless)).toBe(true)
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
            errored.status_reason = 'provider_key_required'
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
                    '/api/projects/:teamId/evaluations/:id/': () => [
                        400,
                        {
                            enabled: ['Add a provider API key to enable this evaluation.'],
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

    describe('filteredEvaluations', () => {
        const enabledEval = evaluationWithKey('eval-enabled', null)
        const disabledEval = { ...evaluationWithKey('eval-disabled', null), enabled: false }

        it('includes disabled evaluations by default and excludes them when hidden', async () => {
            logic.actions.loadEvaluationsSuccess([enabledEval, disabledEval])

            await expectLogic(logic).toMatchValues({
                filteredEvaluations: [enabledEval, disabledEval],
            })

            logic.actions.setShowDisabledEvaluations(false)

            await expectLogic(logic).toMatchValues({
                filteredEvaluations: [enabledEval],
            })
        })

        it('scopes the list to a directory but searches across all directories', async () => {
            const rootEvaluation = evaluationWithKey('root', null)
            const directoryEvaluation = evaluationWithKey('inside', null, 'directory-a')

            router.actions.push(
                combineUrl(urls.aiObservabilityEvaluations(), {
                    directory: 'directory-a',
                }).url
            )
            logic.actions.loadEvaluationsSuccess([rootEvaluation, directoryEvaluation])

            await expectLogic(logic).toMatchValues({
                selectedDirectoryId: 'directory-a',
                displayedEvaluations: [directoryEvaluation],
            })

            logic.actions.setEvaluationsFilter('root')

            await expectLogic(logic).toMatchValues({
                displayedEvaluations: [rootEvaluation],
            })
        })

        it('does not reload evaluations when the selected directory changes', async () => {
            const evaluation = evaluationWithKey('local-state', null)
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.loadEvaluationsSuccess([evaluation])

            router.actions.push(
                combineUrl(urls.aiObservabilityEvaluations(), {
                    directory: 'directory-a',
                }).url
            )
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.evaluations).toEqual([evaluation])
        })

        it('restores an evaluation in server list order', async () => {
            const newerEvaluation = {
                ...evaluationWithKey('newer', null),
                created_at: '2024-02-01T00:00:00Z',
            }
            const olderEvaluation = evaluationWithKey('older', null)
            logic.actions.loadEvaluationsSuccess([newerEvaluation])

            logic.actions.restoreEvaluationSuccess(olderEvaluation)

            expect(logic.values.evaluations).toEqual([newerEvaluation, olderEvaluation])
        })
    })

    describe('detectorEvaluationIds', () => {
        it('lists only evaluations whose true result is a failure', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadEvaluationsSuccess([
                    evaluationWithOutputConfig('detector', { true_is_failure: true }),
                    evaluationWithOutputConfig('quality', { true_is_failure: false }),
                    evaluationWithOutputConfig('legacy', {}),
                ])
            }).toMatchValues({ detectorEvaluationIds: ['detector'] })
        })
    })

    describe('evaluationsLoading', () => {
        it('clears when no team is available, instead of hanging forever', async () => {
            // A hard load straight onto a scene before the team resolves is a real way to hit
            // this: currentTeamId reads null, and the loader must still settle.
            teamLogic.actions.loadCurrentTeamSuccess(null)

            await expectLogic(logic, () => {
                logic.actions.loadEvaluations()
            }).toDispatchActions(['loadEvaluations', 'loadEvaluationsFailure'])

            expect(logic.values.evaluationsLoading).toBe(false)
        })
    })

    describe('evaluationsSettled', () => {
        it('is false while never-started and loading look identical on evaluationsLoading, then flips true on success', async () => {
            // beforeEach's mount() has already dispatched loadEvaluations synchronously, so the
            // fetch is in flight here: evaluationsLoading is true, but settling hasn't happened.
            expect(logic.values.evaluationsSettled).toBe(false)

            await expectLogic(logic).toDispatchActions(['loadEvaluationsSuccess'])

            expect(logic.values.evaluationsSettled).toBe(true)
        })

        it('flips true on failure too, unlike evaluationsLoading which reads the same as never-started', async () => {
            teamLogic.actions.loadCurrentTeamSuccess(null)

            await expectLogic(logic, () => {
                logic.actions.loadEvaluations()
            }).toDispatchActions(['loadEvaluationsFailure'])

            expect(logic.values.evaluationsLoading).toBe(false)
            expect(logic.values.evaluationsSettled).toBe(true)
        })
    })

    describe('waitForEvaluationsSettled', () => {
        it('waits for a pending fetch instead of resolving against an empty evaluations list', async () => {
            let resolveRequest: (value: { results: EvaluationConfig[] }) => void = () => {}
            useMocks({
                get: {
                    '/api/projects/:teamId/evaluations/': () => new Promise((resolve) => (resolveRequest = resolve)),
                },
            })
            logic.unmount()
            logic = llmEvaluationsLogic()
            logic.mount()

            let resolved = false
            const waiting = waitForEvaluationsSettled().then(() => {
                resolved = true
            })

            await Promise.resolve()
            expect(resolved).toBe(false)

            resolveRequest({ results: [] })
            await waiting
            expect(resolved).toBe(true)
        })

        it('resolves immediately once evaluations have already settled', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationsSuccess'])

            await expect(waitForEvaluationsSettled()).resolves.toBeUndefined()
        })

        it('waits again for a refetch instead of resolving against the polarity of the previous list', async () => {
            await expectLogic(logic).toDispatchActions(['loadEvaluationsSuccess'])

            let resolveRefetch: (value: { results: EvaluationConfig[] }) => void = () => {}
            const refetch = new Promise<{ results: EvaluationConfig[] }>((resolve) => (resolveRefetch = resolve))
            useMocks({ get: { '/api/projects/:teamId/evaluations/': () => refetch } })
            logic.actions.loadEvaluations()

            let resolved = false
            const waiting = waitForEvaluationsSettled().then(() => {
                resolved = true
            })

            await Promise.resolve()
            expect(resolved).toBe(false)

            resolveRefetch({ results: [] })
            await waiting
            expect(resolved).toBe(true)
        })
    })
})
