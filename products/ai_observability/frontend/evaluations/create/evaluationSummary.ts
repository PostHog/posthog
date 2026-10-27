import { pluralize } from 'lib/utils/strings'

import { evaluationTarget } from '../evaluationVolume'
import type { EvaluationConfig, EvaluationTarget } from '../types'

const UNIT_NOUNS: Record<EvaluationTarget, string> = {
    generation: 'generations',
    trace: 'traces',
    session: 'sessions',
}

/** What one run covers, such as "each trace". */
export function targetText(evaluation: EvaluationConfig): string {
    return `each ${evaluationTarget(evaluation)}`
}

/** How much traffic the triggers take. Each condition set samples on its own, so several sets get no one percentage. */
export function triggerText(evaluation: EvaluationConfig): string {
    if (evaluation.conditions.length > 1) {
        return `${evaluation.conditions.length} condition sets`
    }
    const [condition] = evaluation.conditions
    const filterCount = (condition?.properties ?? []).length
    return `${condition?.rollout_percentage ?? 0}% of ${filterCount ? 'matching' : 'all'} ${
        UNIT_NOUNS[evaluationTarget(evaluation)]
    }${filterCount ? ` (${pluralize(filterCount, 'filter')})` : ''}`
}

/** How often a report arrives, such as "weekly" or "every 100 results", or "never" when reports are off. */
export function reportText(report: {
    enabled: boolean
    frequency: string
    scheduleCadence: string
    triggerThreshold: number
}): string {
    if (!report.enabled) {
        return 'never'
    }
    if (report.frequency === 'scheduled') {
        return report.scheduleCadence
    }
    return `every ${report.triggerThreshold} results`
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

/** Why reports cannot be turned on yet, or null when they can. Reports read pass rates. */
export function reportsUnavailableReason(evaluation: EvaluationConfig, isReportable: boolean): string | null {
    if (isReportable) {
        return null
    }
    const instructions = evaluation.evaluation_type === 'hog' ? 'code' : 'prompt'
    return evaluation.output_type === 'numeric'
        ? `Reports need a pass rate. Below the ${instructions}, set the score a run needs to pass.`
        : evaluation.output_type === 'categorical'
          ? `Reports need a pass rate. Below the ${instructions}, pick which categories count as a pass.`
          : 'Reports are not available for this kind of evaluation.'
}
