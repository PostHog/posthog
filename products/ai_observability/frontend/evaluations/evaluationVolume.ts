import { humanFriendlyNumber } from 'lib/utils/numbers'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, HogQLMathType } from '~/types'

import type { EvaluationConditionSet, EvaluationTarget } from './types'

/** How far back the estimate looks. A week covers weekday and weekend traffic. */
export const VOLUME_LOOKBACK_DAYS = 7

/** The property that groups generations into one unit of the target. Generations need no grouping. */
const UNIT_PROPERTY: Record<Exclude<EvaluationTarget, 'generation'>, string> = {
    trace: '$ai_trace_id',
    session: '$ai_session_id',
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
                          math_hogql: `count(DISTINCT properties.${UNIT_PROPERTY[target]})`,
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
    return runs === 1 ? 'once a week' : `about ${runs} times a week`
}
