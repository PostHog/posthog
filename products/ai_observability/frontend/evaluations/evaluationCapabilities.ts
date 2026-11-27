import { type LLMProviderKey, isUsableProviderKey } from '../settings/llmProviderKeysLogic'
import type { EvaluationConfig, EvaluationOutputType, EvaluationType, LLMJudgeEvaluation } from './types'

// Mirrors REPORTABLE_OUTPUT_TYPES_BY_TARGET in evaluation_configs.py — keep the two in step.
const REPORTABLE_OUTPUT_TYPES_BY_TARGET: Record<string, ReadonlySet<EvaluationOutputType>> = {
    generation: new Set(['boolean', 'sentiment', 'numeric', 'categorical']),
    trace: new Set(['boolean', 'numeric', 'categorical']),
    session: new Set(['boolean', 'numeric', 'categorical']),
}

export function isBooleanEvaluationOutput(outputType: EvaluationOutputType | null | undefined): boolean {
    return outputType === 'boolean'
}

export function evaluationSupportsReportHistory(
    evaluation: Pick<EvaluationConfig, 'output_type' | 'target'> | null | undefined
): boolean {
    return !!evaluation && (REPORTABLE_OUTPUT_TYPES_BY_TARGET[evaluation.target]?.has(evaluation.output_type) ?? false)
}

export function evaluationSupportsReports(
    evaluation:
        | (Pick<EvaluationConfig, 'output_type' | 'target'> & Partial<Pick<EvaluationConfig, 'output_config'>>)
        | null
        | undefined
): boolean {
    return (
        evaluationSupportsReportHistory(evaluation) &&
        (!['numeric', 'categorical'].includes(evaluation?.output_type ?? '') ||
            !!evaluation?.output_config?.passing_rule)
    )
}

export function evaluationSupportsRunOutcomes(
    evaluation:
        | (Pick<EvaluationConfig, 'output_type' | 'target'> & Partial<Pick<EvaluationConfig, 'output_config'>>)
        | null
        | undefined
): boolean {
    return evaluation?.output_type === 'numeric' || evaluation?.output_type === 'categorical'
        ? !!evaluation.output_config?.passing_rule
        : isBooleanEvaluationOutput(evaluation?.output_type)
}

export function evaluationTypeUsesModelConfiguration(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationType === 'llm_judge'
}

// Sessions are creatable through the API and MCP regardless of the UI flag, so an evaluation that
// already targets one must keep the option listed even for a flag-off user. Without it the picker
// falls back to rendering the raw 'session' value, and saving would silently drop the target.
export function evaluationOffersSessionTarget(
    evaluation: Pick<EvaluationConfig, 'target'> | null | undefined,
    settlingStrategyEnabled: boolean
): boolean {
    return settlingStrategyEnabled || evaluation?.target === 'session'
}

export function isLLMJudgeEvaluation(
    evaluation: EvaluationConfig | null | undefined
): evaluation is LLMJudgeEvaluation {
    return evaluation?.evaluation_type === 'llm_judge'
}

export function evaluationTypeUsesProviderKey(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationTypeUsesModelConfiguration(evaluationType)
}

/** Enabling a judge needs a pinned key. */
export function evaluationCanResolveModel(
    evaluation: Pick<EvaluationConfig, 'evaluation_type' | 'model_configuration'>
): boolean {
    return (
        !evaluationTypeUsesProviderKey(evaluation.evaluation_type) || !!evaluation.model_configuration?.provider_key_id
    )
}

/** Why a judge can't be turned on yet, or null when it can. */
export function evaluationEnableBlockedReason(
    evaluation: Pick<EvaluationConfig, 'evaluation_type' | 'model_configuration'>,
    providerKeys: Pick<LLMProviderKey, 'state' | 'can_use'>[]
): string | null {
    if (evaluationCanResolveModel(evaluation)) {
        return null
    }
    return providerKeys.some(isUsableProviderKey)
        ? 'Choose a model with a provider API key to enable this evaluation.'
        : 'Add a provider API key, then choose a model with it to enable this evaluation.'
}

export function evaluationTypeDefaultsToBooleanOutput(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationType === 'llm_judge' || evaluationType === 'hog'
}
