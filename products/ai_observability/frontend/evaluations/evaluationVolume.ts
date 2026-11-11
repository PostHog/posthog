import { humanFriendlyNumber } from 'lib/utils/numbers'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, HogQLMathType } from '~/types'

import type { EvaluationConditionSet, EvaluationConfig, EvaluationTarget } from './types'

/** How far back the estimate looks. A week covers weekday and weekend traffic. */
export const VOLUME_LOOKBACK_DAYS = 7

/** What one run evaluates. Sentiment always reads single generations, whatever target the row stores. */
export function evaluationTarget(evaluation: EvaluationConfig): EvaluationTarget {
    return evaluation.evaluation_type === 'sentiment' ? 'generation' : evaluation.target
}

// Ingestion keeps these only on AI events storage, so a filter on them matches nothing in the events the estimate counts.
const CONTENT_PROPERTIES = new Set([
    '$ai_input',
    '$ai_output',
    '$ai_output_choices',
    '$ai_input_state',
    '$ai_output_state',
    '$ai_tools',
])

export function filtersOnContent(conditions: EvaluationConditionSet[]): boolean {
    return conditions.some((condition) =>
        (condition.properties ?? []).some(
            (property) => 'key' in property && CONTENT_PROPERTIES.has(String(property.key))
        )
    )
}

const HAS_TRACE_ID = "notEmpty(coalesce(properties.$ai_trace_id, ''))"

/** The scheduler skips a generation without a trace ID, and a session evaluation also needs a session ID. */
const UNIT_COUNT_HOGQL: Record<Exclude<EvaluationTarget, 'generation'>, string> = {
    trace: `countDistinctIf(properties.$ai_trace_id, ${HAS_TRACE_ID})`,
    session: `countDistinctIf(properties.$ai_session_id, ${HAS_TRACE_ID} AND notEmpty(coalesce(properties.$ai_session_id, '')))`,
}

/**
 * Counts what one condition set matched over the lookback: every matching generation, and for a trace or session
 * target the distinct traces or sessions among them. Evaluations only run on `$ai_generation` events.
 */
export function conditionVolumeQuery(condition: EvaluationConditionSet, target: EvaluationTarget): TrendsQuery {
    const base = {
        kind: NodeKind.EventsNode as const,
        event: '$ai_generation',
        properties: condition.properties ?? [],
    }
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            { ...base, math: BaseMathType.TotalCount },
            ...(target === 'generation'
                ? []
                : [
                      {
                          ...base,
                          math: HogQLMathType.HogQL,
                          math_hogql: UNIT_COUNT_HOGQL[target],
                      },
                  ]),
        ],
        dateRange: { date_from: `-${VOLUME_LOOKBACK_DAYS}d` },
        interval: 'day',
        trendsFilter: { display: ChartDisplayType.BoldNumber },
    }
}

export interface ConditionCounts {
    generations: number
    /** Units of the target: generations, or distinct traces or sessions. */
    units: number
}

export interface ConditionVolume extends ConditionCounts {
    rolloutPercentage: number
}

export interface VolumeEstimate {
    target: EvaluationTarget
    /** Generations that matched any condition set. Overlapping sets count a generation once per set. */
    matchingGenerations: number
    matchingUnits: number
    /** Runs the evaluation would have made over the lookback, after sampling. */
    runs: number
}

export function summarizeVolume(conditions: ConditionVolume[], target: EvaluationTarget): VolumeEstimate {
    return {
        target,
        matchingGenerations: conditions.reduce((sum, condition) => sum + condition.generations, 0),
        matchingUnits: conditions.reduce((sum, condition) => sum + condition.units, 0),
        runs: Math.round(
            conditions.reduce((sum, condition) => sum + (condition.units * condition.rolloutPercentage) / 100, 0)
        ),
    }
}

/** How often the evaluation runs, from its runs over the lookback, such as "about 14 times a day". */
export function runRate(runs: number): string {
    const perDay = Math.round(runs / VOLUME_LOOKBACK_DAYS)
    if (perDay >= 2) {
        return `about ${humanFriendlyNumber(perDay)} times a day`
    }
    if (perDay === 1) {
        return 'about once a day'
    }
    if (runs === 0) {
        return 'less than once a week'
    }
    return runs === 1 ? 'once a week' : `about ${runs} times a week`
}
