import { pluralize } from 'lib/utils/strings'

import { settleStrategy } from '../constants'
import { evaluationTarget } from '../evaluationVolume'
import {
    DEFAULT_SESSION_MAX_AGE_SECONDS,
    DEFAULT_SESSION_QUIET_PERIOD_SECONDS,
    DEFAULT_SESSION_WINDOW_SECONDS,
    DEFAULT_TRACE_MAX_AGE_SECONDS,
    DEFAULT_TRACE_QUIET_PERIOD_SECONDS,
    DEFAULT_TRACE_WINDOW_SECONDS,
} from '../llmEvaluationLogic'
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
    return evaluation.output_type === 'numeric'
        ? 'Reports need a pass rate. In the Returns step, set the score a run needs to pass.'
        : evaluation.output_type === 'categorical'
          ? 'Reports need a pass rate. In the Returns step, pick which categories count as a pass.'
          : 'Reports are not available for this kind of evaluation.'
}

const DURATION_UNITS: [string, number][] = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
    ['second', 1],
]

/** A duration in its largest whole unit, such as "30 minutes". The duration picker only stores whole units. */
export function durationInWords(seconds: number): string {
    const [unit, size] = DURATION_UNITS.find(([, unitSize]) => seconds % unitSize === 0) ?? ['second', 1]
    return pluralize(seconds / size, unit)
}

/** When a trace or session run starts, in one sentence, so the timing settings can stay folded away. */
export function settleSummary(evaluation: EvaluationConfig): string | null {
    if (evaluation.target !== 'trace' && evaluation.target !== 'session') {
        return null
    }
    const isSession = evaluation.target === 'session'
    const config = evaluation.target_config
    const duration = durationInWords
    if (settleStrategy(config.strategy, evaluation.target) === 'fixed_window') {
        const wait =
            config.window_seconds ?? (isSession ? DEFAULT_SESSION_WINDOW_SECONDS : DEFAULT_TRACE_WINDOW_SECONDS)
        return `It runs ${duration(wait)} after the first matching generation.`
    }
    const quiet =
        config.quiet_period_seconds ??
        (isSession ? DEFAULT_SESSION_QUIET_PERIOD_SECONDS : DEFAULT_TRACE_QUIET_PERIOD_SECONDS)
    const maxAge =
        config.max_age_seconds ?? (isSession ? DEFAULT_SESSION_MAX_AGE_SECONDS : DEFAULT_TRACE_MAX_AGE_SECONDS)
    return `It runs once the ${evaluation.target} has been quiet for ${duration(quiet)}, or ${duration(maxAge)} after it starts.`
}
