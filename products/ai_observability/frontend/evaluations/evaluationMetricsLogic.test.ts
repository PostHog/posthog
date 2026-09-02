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

const evaluation = (id: string, directoryId: string | null, name = `Evaluation ${id}`): LLMJudgeEvaluation => ({
    id,
    name,
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

    it('uses one filtered breakdown query and scopes metrics to the selected directory', () => {
        const firstRootEvaluation = evaluation('root-one', null, "Root's evaluation")
        const secondRootEvaluation = evaluation('root-two', null, "Root's evaluation")
        const directoryEvaluation = evaluation('inside', 'directory-a')

        evaluationsLogic.actions.loadEvaluationsSuccess([
            firstRootEvaluation,
            secondRootEvaluation,
            directoryEvaluation,
        ])
        metricsLogic.actions.loadStatsSuccess([
            stats(firstRootEvaluation.id, 4),
            stats(secondRootEvaluation.id, 3),
            stats(directoryEvaluation.id, 2),
        ])

        expect(metricsLogic.values.chartQuery?.series).toEqual([
            expect.objectContaining({
                properties: [expect.objectContaining({ value: [firstRootEvaluation.id, secondRootEvaluation.id] })],
            }),
        ])
        expect(metricsLogic.values.chartQuery?.breakdownFilter).toEqual(
            expect.objectContaining({
                breakdown_type: 'hogql',
                breakdown_hide_other_aggregation: true,
            })
        )
        expect(metricsLogic.values.chartQuery?.breakdownFilter?.breakdown).toContain("'Root\\'s evaluation (1)'")
        expect(metricsLogic.values.chartQuery?.breakdownFilter?.breakdown).toContain("'Root\\'s evaluation (2)'")
        expect(metricsLogic.values.summaryMetrics.total_runs).toBe(7)

        router.actions.push(
            combineUrl(urls.aiObservabilityEvaluations(), {
                directory: 'directory-a',
            }).url
        )

        expect(metricsLogic.values.chartQuery?.series).toEqual([
            expect.objectContaining({
                properties: [expect.objectContaining({ value: [directoryEvaluation.id] })],
            }),
        ])
        expect(metricsLogic.values.chartQuery?.breakdownFilter?.breakdown).toContain(directoryEvaluation.name)
        expect(metricsLogic.values.chartQuery?.breakdownFilter?.breakdown).not.toContain(firstRootEvaluation.id)
        expect(metricsLogic.values.summaryMetrics.total_runs).toBe(2)
    })
})
