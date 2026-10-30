import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'
import { ChartDisplayType, HogQLMathType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    EVALUATION_BOOLEAN_GRADED_HOGQL,
    EVALUATION_CATEGORICAL_GRADED_HOGQL,
    EVALUATION_NUMERIC_GRADED_HOGQL,
    categoricalEvaluationsPassedHogQL,
    evaluationIsDetector,
    evaluationPassedHogQLForMany,
    evaluationPassRateHogQL,
    numericEvaluationPassedHogQL,
} from './constants'
import { EvaluationConfig } from './types'

const MAX_EVALUATION_CHART_SERIES = 10

function hasPassRate(evaluation: EvaluationConfig): boolean {
    return (
        evaluation.output_type === 'boolean' ||
        (['numeric', 'categorical'].includes(evaluation.output_type) && !!evaluation.output_config.passing_rule)
    )
}

function buildEvaluationBreakdownExpression(evaluations: EvaluationConfig[]): string {
    const evaluationNameCounts = new Map<string, number>()
    const evaluationNameIndexes = new Map<string, number>()

    for (const evaluation of evaluations) {
        evaluationNameCounts.set(evaluation.name, (evaluationNameCounts.get(evaluation.name) ?? 0) + 1)
    }

    const conditionsAndLabels = evaluations.flatMap((evaluation) => {
        const nameIndex = (evaluationNameIndexes.get(evaluation.name) ?? 0) + 1
        evaluationNameIndexes.set(evaluation.name, nameIndex)
        const label =
            evaluationNameCounts.get(evaluation.name) === 1 ? evaluation.name : `${evaluation.name} (${nameIndex})`

        return [`properties.$ai_evaluation_id = ${escapeHogQLString(evaluation.id)}`, escapeHogQLString(label)]
    })

    return `multiIf(${conditionsAndLabels.join(', ')}, toString(properties.$ai_evaluation_id))`
}

/** Pass rate over time with one line per evaluation, or null when none of them has a pass rate. Callers pick which evaluations to chart. */
export function buildEvaluationPassRateTrendsQuery(
    evaluations: EvaluationConfig[],
    dateFilter: { dateFrom: string | null; dateTo: string | null },
    interval: 'hour' | 'day'
): TrendsQuery | null {
    const charted = evaluations
        .filter((evaluation) => !evaluation.deleted && hasPassRate(evaluation))
        .slice(0, MAX_EVALUATION_CHART_SERIES)

    if (charted.length === 0) {
        return null
    }

    const dateFrom = dateFilter.dateFrom || '-7d'
    const dateTo = dateFilter.dateTo || null
    const numericEvaluations = charted.filter((evaluation) => evaluation.output_type === 'numeric')
    let passedExpression = evaluationPassedHogQLForMany(
        charted.filter(evaluationIsDetector).map((evaluation) => evaluation.id)
    )
    let gradedExpression = EVALUATION_BOOLEAN_GRADED_HOGQL
    if (numericEvaluations.length > 0) {
        const numericCases = numericEvaluations.flatMap((evaluation) => [
            `properties.$ai_evaluation_id = ${escapeHogQLString(evaluation.id)}`,
            numericEvaluationPassedHogQL(evaluation),
        ])
        const numericIds = numericEvaluations.map((evaluation) => escapeHogQLString(evaluation.id)).join(', ')
        passedExpression = `multiIf(${numericCases.join(', ')}, ${passedExpression})`
        gradedExpression = `if(properties.$ai_evaluation_id IN (${numericIds}), ${EVALUATION_NUMERIC_GRADED_HOGQL}, ${EVALUATION_BOOLEAN_GRADED_HOGQL})`
    }

    if (charted.some((evaluation) => evaluation.output_type === 'categorical')) {
        passedExpression = `if(properties.$ai_evaluation_result_type = 'categorical', ${categoricalEvaluationsPassedHogQL(charted)}, ${passedExpression})`
        gradedExpression = `if(properties.$ai_evaluation_result_type = 'categorical', ${EVALUATION_CATEGORICAL_GRADED_HOGQL}, ${gradedExpression})`
    }

    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$ai_evaluation',
                math: HogQLMathType.HogQL,
                math_hogql: evaluationPassRateHogQL(passedExpression, gradedExpression),
                properties: [
                    {
                        key: '$ai_evaluation_id',
                        value: charted.map((evaluation) => evaluation.id),
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ],
            },
        ],
        breakdownFilter: {
            breakdown: buildEvaluationBreakdownExpression(charted),
            breakdown_type: 'hogql',
            breakdown_limit: MAX_EVALUATION_CHART_SERIES,
            breakdown_hide_other_aggregation: true,
        },
        trendsFilter: {
            display: ChartDisplayType.ActionsLineGraph,
        },
        dateRange: {
            date_from: dateFrom,
            date_to: dateTo,
        },
        interval,
    }
}
