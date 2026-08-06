import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { evaluationMetricsLogic, EvaluationStats } from './evaluationMetricsLogic'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { LLMJudgeEvaluation } from './types'

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')

    return {
        __esModule: true,
        ...actual,
        default: {
            ...actual.default,
            query: jest.fn().mockResolvedValue({ results: [] }),
        },
    }
})

const evaluation = (id: string, directoryId: string | null): LLMJudgeEvaluation => ({
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
    conditions: [{ id: `condition-${id}`, rollout_percentage: 100, properties: [] }],
    target: 'generation',
    target_config: {},
    model_configuration: null,
    total_runs: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
})

const stats = (evaluationId: string, runsCount: number): EvaluationStats => ({
    evaluation_id: evaluationId,
    runs_count: runsCount,
    applicable_count: runsCount,
    pass_count: runsCount,
    pass_rate: 100,
    applicability_rate: 100,
})

describe('evaluationMetricsLogic', () => {
    let evaluationsLogic: ReturnType<typeof llmEvaluationsLogic.build>
    let metricsLogic: ReturnType<typeof evaluationMetricsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/': { results: [] },
                '/api/projects/:teamId/evaluation_directories/': [],
            },
        })
        initKeaTests()
        evaluationsLogic = llmEvaluationsLogic()
        evaluationsLogic.mount()
        metricsLogic = evaluationMetricsLogic()
        metricsLogic.mount()

        await expectLogic(metricsLogic, () => metricsLogic.actions.loadStats()).toFinishAllListeners()
    })

    afterEach(() => {
        metricsLogic.unmount()
        evaluationsLogic.unmount()
    })

    it('scopes the graph and summary metrics when a directory is selected', () => {
        const rootEvaluation = evaluation('root', null)
        const directoryEvaluation = evaluation('inside', 'directory-a')

        evaluationsLogic.actions.loadEvaluationsSuccess([rootEvaluation, directoryEvaluation])
        metricsLogic.actions.loadStatsSuccess([stats(rootEvaluation.id, 4), stats(directoryEvaluation.id, 2)])

        expect(metricsLogic.values.chartQuery?.series).toEqual([
            expect.objectContaining({ custom_name: rootEvaluation.name }),
        ])
        expect(metricsLogic.values.summaryMetrics.total_runs).toBe(4)

        router.actions.push(
            combineUrl(urls.aiObservabilityEvaluations(), {
                directory: 'directory-a',
            }).url
        )

        expect(metricsLogic.values.chartQuery?.series).toEqual([
            expect.objectContaining({ custom_name: directoryEvaluation.name }),
        ])
        expect(metricsLogic.values.summaryMetrics.total_runs).toBe(2)
    })
})
