import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EVALUATION_NOT_SKIPPED_HOGQL, EVALUATION_RESULT_TRUE_HOGQL } from './constants'
import { evaluationMetricsLogic, EvaluationStatsRow } from './evaluationMetricsLogic'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { LLMJudgeEvaluation } from './types'

const queryMock = jest.fn().mockResolvedValue({ results: [] })

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')

    return {
        __esModule: true,
        ...actual,
        default: {
            ...actual.default,
            query: (...args: unknown[]) => queryMock(...args),
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

const stats = (evaluationId: string, runsCount: number, trueCount = runsCount): EvaluationStatsRow => ({
    evaluation_id: evaluationId,
    runs_count: runsCount,
    applicable_count: runsCount,
    true_count: trueCount,
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

    it('reads a detector pass rate from its false results', () => {
        const detector = { ...evaluation('detector', null), output_config: { true_is_failure: true } }
        const quality = evaluation('quality', null)

        evaluationsLogic.actions.loadEvaluationsSuccess([detector, quality])
        metricsLogic.actions.loadStatsSuccess([stats('detector', 100, 80), stats('quality', 100, 80)])

        expect(metricsLogic.values.evaluationsWithMetrics).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ id: 'detector', stats: expect.objectContaining({ pass_rate: 20 }) }),
                expect.objectContaining({ id: 'quality', stats: expect.objectContaining({ pass_rate: 80 }) }),
            ])
        )
    })

    it('scopes the chart pass expression to a detector among the enabled evaluations', () => {
        const detector = { ...evaluation('detector', null), output_config: { true_is_failure: true } }
        const quality = evaluation('quality', null)

        evaluationsLogic.actions.loadEvaluationsSuccess([detector, quality])
        metricsLogic.actions.loadStatsSuccess([stats('detector', 10, 2), stats('quality', 10, 8)])

        const mathHogql = metricsLogic.values.chartQuery?.series?.[0].math_hogql ?? ''
        expect(mathHogql).toContain("properties.$ai_evaluation_id IN ('detector')")
        expect(mathHogql).toContain("properties.$ai_evaluation_result = 'false'")
        // Both sides of the ratio drop skipped runs — otherwise the false a skip stores reads as
        // a detector pass, and the chart disagrees with the list, which already excludes them.
        expect(mathHogql).toContain(`AND ${EVALUATION_NOT_SKIPPED_HOGQL}) /`)
        expect(mathHogql).toContain(`IS NOT NULL AND ${EVALUATION_NOT_SKIPPED_HOGQL}`)
    })

    it('excludes skipped runs from both counts, so a detector cannot count them as a pass', async () => {
        await expectLogic(metricsLogic, () => metricsLogic.actions.loadStats()).toFinishAllListeners()

        const query = queryMock.mock.calls.at(-1)?.[0]
        expect(query.query).toContain(`IS NOT NULL AND ${EVALUATION_NOT_SKIPPED_HOGQL}`)
        expect(query.query).toContain(`${EVALUATION_RESULT_TRUE_HOGQL} AND ${EVALUATION_NOT_SKIPPED_HOGQL}`)
    })
})
