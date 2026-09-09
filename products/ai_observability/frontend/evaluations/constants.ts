import { escapeHogQLString } from '~/queries/utils'

import type { EvaluationConfig } from './types'

// Most-recent runs fetched for an evaluation's runs table and its result badges
export const EVALUATION_RUNS_QUERY_LIMIT = 250

// Compared against the string 'true', not `= true` or `= 1`: HogQL types $ai_evaluation_result from
// each team's own property definition, so teams that haven't registered it as Boolean extract the
// JSON bool as the string 'true' (where a numeric literal throws), while Boolean-registered teams
// still compare correctly against the string form. Reading the property directly rather than via
// JSONExtractString keeps the lookup on the properties_group_ai column and its bloom filter index.
// Same reasoning as the predicates in posthog/temporal/ai_observability/eval_reports/output_types.py.
export const EVALUATION_RESULT_TRUE_HOGQL = "properties.$ai_evaluation_result = 'true'"
const EVALUATION_RESULT_FALSE_HOGQL = "properties.$ai_evaluation_result = 'false'"

// A skipped run was never graded, but an evaluation that disallows N/A still emits result=false
// alongside skipped=true, so any count that doesn't exclude skips reads them as failures. Mirrors
// _NOT_SKIPPED_PREDICATE in posthog/temporal/ai_observability/eval_reports/output_types.py, which
// the report metrics already apply — without this the two surfaces disagree about the same runs.
export const EVALUATION_NOT_SKIPPED_HOGQL =
    "(isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')"

/** A detector looks for a problem, so its true result is the undesirable one. */
export function evaluationIsDetector(evaluation: Pick<EvaluationConfig, 'output_config'>): boolean {
    return evaluation.output_config.true_is_failure === true
}

/** The HogQL that counts a pass for one evaluation. */
export function evaluationPassedHogQL(evaluation: Pick<EvaluationConfig, 'output_config'>): string {
    return evaluationIsDetector(evaluation) ? EVALUATION_RESULT_FALSE_HOGQL : EVALUATION_RESULT_TRUE_HOGQL
}

/**
 * The HogQL for a pass rate, as a percentage of the graded runs. Skipped runs leave both sides of
 * the ratio, so a detector never reads the false a skip stores as a pass.
 */
export function evaluationPassRateHogQL(passedExpression: string): string {
    const graded = `countIf(properties.$ai_evaluation_result IS NOT NULL AND ${EVALUATION_NOT_SKIPPED_HOGQL})`
    return `if(${graded} > 0, countIf((${passedExpression}) AND ${EVALUATION_NOT_SKIPPED_HOGQL}) / ${graded} * 100, 0)`
}

/** The HogQL that counts a pass across many evaluations at once, for a grouped or broken-down query. */
export function evaluationPassedHogQLForMany(detectorEvaluationIds: string[]): string {
    if (detectorEvaluationIds.length === 0) {
        return EVALUATION_RESULT_TRUE_HOGQL
    }
    const ids = detectorEvaluationIds.map((id) => escapeHogQLString(id)).join(', ')
    return `if(properties.$ai_evaluation_id IN (${ids}), ${EVALUATION_RESULT_FALSE_HOGQL}, ${EVALUATION_RESULT_TRUE_HOGQL})`
}
