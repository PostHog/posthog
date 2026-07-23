import type { LLMProviderKey } from '../settings/llmProviderKeysLogic'
import type { EvaluationConfig, EvaluationOutputType, EvaluationType, LLMJudgeEvaluation } from './types'

const REPORTABLE_OUTPUT_TYPES: ReadonlySet<EvaluationOutputType> = new Set(['boolean', 'sentiment'])

export function isBooleanEvaluationOutput(outputType: EvaluationOutputType | null | undefined): boolean {
    return outputType === 'boolean'
}

export function evaluationSupportsReports(
    evaluation: Pick<EvaluationConfig, 'output_type' | 'target'> | null | undefined
): boolean {
    if (evaluation?.output_type == null || !REPORTABLE_OUTPUT_TYPES.has(evaluation.output_type)) {
        return false
    }
    return evaluation.target === 'generation' || (evaluation.target === 'trace' && evaluation.output_type === 'boolean')
}

export function evaluationSupportsRunSummary(
    evaluation: Pick<EvaluationConfig, 'output_type' | 'target'> | null | undefined
): boolean {
    return evaluation?.target === 'generation' && isBooleanEvaluationOutput(evaluation.output_type)
}

export function evaluationTypeUsesModelConfiguration(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationType === 'llm_judge'
}

export function isLLMJudgeEvaluation(
    evaluation: EvaluationConfig | null | undefined
): evaluation is LLMJudgeEvaluation {
    return evaluation?.evaluation_type === 'llm_judge'
}

export function evaluationTypeUsesProviderKey(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationTypeUsesModelConfiguration(evaluationType)
}

export function evaluationCanResolveModel(
    evaluation: Pick<EvaluationConfig, 'evaluation_type' | 'model_configuration'>,
    // undefined = the team's evaluation config hasn't loaded yet — stay permissive rather than
    // flashing a disabled state; null = loaded, and there is no active key.
    activeProviderKey: Pick<LLMProviderKey, 'provider' | 'state'> | null | undefined
): boolean {
    if (!evaluationTypeUsesProviderKey(evaluation.evaluation_type)) {
        return true
    }
    if (evaluation.model_configuration?.provider_key_id) {
        return true
    }
    if (activeProviderKey === undefined) {
        return true
    }
    // No pinned key: the eval falls back to the team's active key, which must be healthy and —
    // when the eval has an explicit model configuration — belong to the same provider (mirrors
    // `active_key_fallback` in model_resolution.py).
    if (activeProviderKey === null || activeProviderKey.state !== 'ok') {
        return false
    }
    return !evaluation.model_configuration || evaluation.model_configuration.provider === activeProviderKey.provider
}

export function evaluationTypeDefaultsToBooleanOutput(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationType === 'llm_judge' || evaluationType === 'hog'
}

export function evaluationTypeHasEditableCriteria(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationTypeDefaultsToBooleanOutput(evaluationType)
}
