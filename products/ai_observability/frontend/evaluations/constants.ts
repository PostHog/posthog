import { escapeHogQLString } from '~/queries/utils'

import type { EvaluationConfig, EvaluationOutputConfig } from './types'

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

export function numericOutputConfigError(config: EvaluationOutputConfig): string | null {
    const { min, max, step } = config
    const passing_rule = config.passing_rule && 'threshold' in config.passing_rule ? config.passing_rule : null
    if ([min, max, step, passing_rule?.threshold].some((value) => value != null && !Number.isFinite(value))) {
        return 'Enter finite numbers for the score bounds, step, and threshold.'
    }
    if (min != null && max != null && min > max) {
        return 'Minimum must be less than or equal to maximum.'
    }
    if (step != null && step <= 0) {
        return 'Step must be greater than zero.'
    }
    if (
        passing_rule &&
        ((min != null && passing_rule.threshold < min) || (max != null && passing_rule.threshold > max))
    ) {
        return 'Set the passing threshold within the score bounds.'
    }
    return null
}

export const EVALUATION_NUMERIC_GRADED_HOGQL = `properties.$ai_evaluation_result_type = 'numeric' AND properties.$ai_evaluation_numeric_result IS NOT NULL AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != 'false') AND ${EVALUATION_NOT_SKIPPED_HOGQL}`
export const EVALUATION_BOOLEAN_GRADED_HOGQL = `(isNull(properties.$ai_evaluation_result_type) OR properties.$ai_evaluation_result_type = 'boolean') AND properties.$ai_evaluation_result IS NOT NULL AND ${EVALUATION_NOT_SKIPPED_HOGQL}`
export const EVALUATION_NUMERIC_MEAN_HOGQL = `avgIf(toFloat(properties.$ai_evaluation_numeric_result), ${EVALUATION_NUMERIC_GRADED_HOGQL})`

export function numericEvaluationPassedHogQL(evaluation: Pick<EvaluationConfig, 'output_config'>): string {
    const rule = evaluation.output_config.passing_rule
    if (!rule || !('threshold' in rule) || !Number.isFinite(rule.threshold)) {
        return 'false'
    }
    return `toFloat(properties.$ai_evaluation_numeric_result) ${rule.operator === 'gte' ? '>=' : '<='} ${rule.threshold}`
}

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
export function evaluationPassRateHogQL(
    passedExpression: string,
    gradedExpression = EVALUATION_BOOLEAN_GRADED_HOGQL
): string {
    return `countIf((${passedExpression}) AND (${gradedExpression})) / nullIf(countIf(${gradedExpression}), 0) * 100`
}

/** The HogQL that counts a pass across many evaluations at once, for a grouped or broken-down query. */
export function evaluationPassedHogQLForMany(detectorEvaluationIds: string[]): string {
    if (detectorEvaluationIds.length === 0) {
        return EVALUATION_RESULT_TRUE_HOGQL
    }
    const ids = detectorEvaluationIds.map((id) => escapeHogQLString(id)).join(', ')
    return `if(properties.$ai_evaluation_id IN (${ids}), ${EVALUATION_RESULT_FALSE_HOGQL}, ${EVALUATION_RESULT_TRUE_HOGQL})`
}

export function formatNumericEvaluationScore(score: number): string {
    return Number(Math.abs(score) >= 1 ? score.toFixed(6) : score.toPrecision(6)).toString()
}

export function numericScorePasses(
    score: number | null | undefined,
    rule: EvaluationOutputConfig['passing_rule']
): boolean | null {
    if (
        score == null ||
        !Number.isFinite(score) ||
        !rule ||
        !('threshold' in rule) ||
        !Number.isFinite(rule.threshold)
    ) {
        return null
    }
    return rule.operator === 'gte' ? score >= rule.threshold : score <= rule.threshold
}

export const EVALUATION_CATEGORIES_HOGQL =
    "JSONExtract(ifNull(properties.$ai_evaluation_categorical_result, '[]'), 'Array(String)')"
export const EVALUATION_CATEGORICAL_GRADED_HOGQL = `properties.$ai_evaluation_result_type = 'categorical' AND properties.$ai_evaluation_categorical_result IS NOT NULL AND (isNull(properties.$ai_evaluation_applicable) OR properties.$ai_evaluation_applicable != 'false') AND ${EVALUATION_NOT_SKIPPED_HOGQL}`

export function categoricalResultPasses(
    categories: string[] | null | undefined,
    rule: EvaluationOutputConfig['passing_rule']
): boolean | null {
    if (categories == null || !rule || !('categories' in rule)) {
        return null
    }
    return categories.every((category) => rule.categories.includes(category))
}

export function categoricalEvaluationPassedHogQL(evaluation: Pick<EvaluationConfig, 'output_config'>): string {
    const rule = evaluation.output_config.passing_rule
    if (!rule || !('categories' in rule)) {
        return 'false'
    }
    const categories = rule.categories.map(escapeHogQLString).join(', ')
    return `hasAll([${categories}], ${EVALUATION_CATEGORIES_HOGQL})`
}

export function categoricalOutputConfigError(config: EvaluationOutputConfig): string | null {
    if (!config.options?.length) {
        return 'Add at least one category.'
    }
    if (
        config.options.some(
            ({ key, label }) =>
                !/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(key) || key.length > 128 || !label.trim() || label.length > 256
        )
    ) {
        return 'Give each category a label and a key using lowercase letters, numbers, underscores, or hyphens.'
    }
    if (new Set(config.options.map(({ key }) => key)).size !== config.options.length) {
        return 'Use a different key for each category.'
    }
    const rule = config.passing_rule
    if (
        rule &&
        (!('categories' in rule) ||
            rule.categories.some((key) => !config.options?.some((option) => option.key === key)))
    ) {
        return 'Choose passing categories from the configured categories.'
    }
    return null
}

export function categoricalEvaluationsPassedHogQL(
    evaluations: Pick<EvaluationConfig, 'id' | 'output_type' | 'output_config'>[]
): string {
    const rules = evaluations.flatMap((evaluation) => {
        const rule = evaluation.output_config.passing_rule
        return evaluation.output_type === 'categorical' && rule && 'categories' in rule
            ? [{ id: evaluation.id, categories: rule.categories }]
            : []
    })
    if (!rules.length) {
        return 'false'
    }
    const ids = rules.map(({ id }) => escapeHogQLString(id)).join(', ')
    const categories = rules.map(({ categories }) => `[${categories.map(escapeHogQLString).join(', ')}]`).join(', ')
    const indexes = rules.map((_, index) => index + 1).join(', ')
    return `properties.$ai_evaluation_id IN (${ids}) AND hasAll(arrayElement([${categories}], transform(properties.$ai_evaluation_id, [${ids}], [${indexes}], 0)), ${EVALUATION_CATEGORIES_HOGQL})`
}
