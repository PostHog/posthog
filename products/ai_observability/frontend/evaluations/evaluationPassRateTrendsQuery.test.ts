import { EVALUATION_NOT_SKIPPED_HOGQL } from './constants'
import { buildEvaluationPassRateTrendsQuery } from './evaluationPassRateTrendsQuery'
import { LLMJudgeEvaluation } from './types'

const evaluation = (id: string, name = `Evaluation ${id}`): LLMJudgeEvaluation => ({
    id,
    name,
    description: '',
    directory_id: null,
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

const PERIOD = { dateFrom: '-7d', dateTo: null }

describe('buildEvaluationPassRateTrendsQuery', () => {
    it.each(['gte', 'lte'] as const)(
        'charts numeric %s pass rules and skips numeric evaluations without one',
        (operator) => {
            const query = buildEvaluationPassRateTrendsQuery(
                [
                    evaluation('boolean'),
                    {
                        ...evaluation('numeric'),
                        output_type: 'numeric',
                        output_config: { passing_rule: { operator, threshold: 0 } },
                    },
                    { ...evaluation('ungraded'), output_type: 'numeric', output_config: {} },
                ],
                PERIOD,
                'day'
            )

            expect(query?.series[0].properties).toEqual([expect.objectContaining({ value: ['boolean', 'numeric'] })])
            const math = query?.series[0].math_hogql ?? ''
            expect(math).toContain(
                `toFloat(properties.$ai_evaluation_numeric_result) ${operator === 'gte' ? '>=' : '<='} 0`
            )
            expect(math).toContain("properties.$ai_evaluation_id = 'numeric'")
            expect(math).toContain(EVALUATION_NOT_SKIPPED_HOGQL)
        }
    )

    it('returns null when no evaluation has a pass rate', () => {
        const ungraded = { ...evaluation('numeric'), output_type: 'numeric' as const, output_config: {} }
        expect(buildEvaluationPassRateTrendsQuery([ungraded], PERIOD, 'day')).toBeNull()
    })

    it('labels evaluations that share a name apart in one breakdown', () => {
        const query = buildEvaluationPassRateTrendsQuery(
            [evaluation('root-one', "Root's evaluation"), evaluation('root-two', "Root's evaluation")],
            PERIOD,
            'day'
        )

        expect(query?.breakdownFilter).toEqual(
            expect.objectContaining({ breakdown_type: 'hogql', breakdown_hide_other_aggregation: true })
        )
        expect(query?.breakdownFilter?.breakdown).toContain("'Root\\'s evaluation (1)'")
        expect(query?.breakdownFilter?.breakdown).toContain("'Root\\'s evaluation (2)'")
    })

    it('reads a detector pass from its false results and drops skipped runs from both counts', () => {
        const detector = { ...evaluation('detector'), output_config: { true_is_failure: true } }
        const math = buildEvaluationPassRateTrendsQuery([detector, evaluation('quality')], PERIOD, 'day')?.series[0]
            .math_hogql

        expect(math).toContain("properties.$ai_evaluation_id IN ('detector')")
        expect(math).toContain("properties.$ai_evaluation_result = 'false'")
        expect(math).toContain(`AND ${EVALUATION_NOT_SKIPPED_HOGQL})) /`)
        expect(math).toContain(`IS NOT NULL AND ${EVALUATION_NOT_SKIPPED_HOGQL}`)
    })
})
