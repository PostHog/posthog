import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { EvaluationConfig, EvaluationTarget } from '../types'

const UNIT_NOUNS: Record<EvaluationTarget, string> = {
    generation: 'generations',
    trace: 'traces',
    session: 'sessions',
}

const RETURN_LABELS = {
    boolean: 'true or false',
    numeric: 'a score',
    categorical: 'one category',
    categorical_multiple: 'several categories',
    sentiment: 'a sentiment',
} as const

/** What the evaluation runs on, such as "10% of matching traces (2 filters)". */
export function scopeText(evaluation: EvaluationConfig): string {
    if (evaluation.conditions.length > 1) {
        return `${evaluation.conditions.length} condition sets`
    }
    const target = evaluation.evaluation_type === 'sentiment' ? 'generation' : evaluation.target
    const [condition] = evaluation.conditions
    const filterCount = (condition?.properties ?? []).length
    return `${condition?.rollout_percentage ?? 0}% of ${filterCount ? 'matching' : 'all'} ${UNIT_NOUNS[target]}${
        filterCount ? ` (${pluralize(filterCount, 'filter')})` : ''
    }`
}

/** Who does the checking, such as "an LLM judge (gpt-4o-mini)". */
export function methodText(evaluation: EvaluationConfig, usesDecisionModel: boolean, modelName?: string): string {
    const model = modelName ? ` (${modelName})` : ''
    switch (evaluation.evaluation_type) {
        case 'llm_judge':
            return `${usesDecisionModel ? 'a decision model' : 'an LLM judge'}${model}`
        case 'hog':
            return 'your code'
        case 'sentiment':
            return 'a sentiment classifier'
    }
}

/** What each run returns, as the "Return" line reads it. */
export function returnText(evaluation: EvaluationConfig): string {
    if (evaluation.output_type === 'categorical' && evaluation.output_config.selection_mode === 'multiple') {
        return RETURN_LABELS.categorical_multiple
    }
    return RETURN_LABELS[evaluation.output_type]
}

/** One sentence for the whole evaluation, such as "Helpfulness runs an LLM judge on 100% of all traces, about 14 a day." */
export function summarySentence({
    evaluation,
    usesDecisionModel,
    modelName,
    runsPerDay,
}: {
    evaluation: EvaluationConfig
    usesDecisionModel: boolean
    modelName?: string
    runsPerDay: number | null
}): string {
    const name = evaluation.name.trim() || 'This evaluation'
    const rate = runsPerDay !== null ? `, about ${humanFriendlyNumber(runsPerDay)} a day` : ''
    return `${name} runs ${methodText(evaluation, usesDecisionModel, modelName)} on ${scopeText(evaluation)}${rate}.`
}
