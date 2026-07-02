import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { EvaluationConfig, EvaluationOutputType, EvaluationType, LLMJudgeEvaluation } from './types'

export function isBooleanEvaluationOutput(outputType: EvaluationOutputType | null | undefined): boolean {
    return outputType === 'boolean'
}

export function evaluationSupportsReports(
    evaluation: Pick<EvaluationConfig, 'output_type' | 'target'> | null | undefined
): boolean {
    // Trace-level evals aren't supported by the report agent yet — the backend rejects
    // report creation for them, so hide the report UI rather than surface that error.
    return isBooleanEvaluationOutput(evaluation?.output_type) && evaluation?.target !== 'trace'
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

export function evaluationTypeDefaultsToBooleanOutput(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationType === 'llm_judge' || evaluationType === 'hog'
}

export function evaluationTypeHasEditableCriteria(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationTypeDefaultsToBooleanOutput(evaluationType)
}

export function evaluationTypeSupportsSignalEmission(evaluationType: EvaluationType | null | undefined): boolean {
    return evaluationType === 'llm_judge'
}

export function evaluationTypeCanBeCreated(
    evaluationType: EvaluationType,
    featureFlags: FeatureFlagsSet | null | undefined
): boolean {
    return evaluationType !== 'sentiment' || !!featureFlags?.[FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_SENTIMENT]
}
