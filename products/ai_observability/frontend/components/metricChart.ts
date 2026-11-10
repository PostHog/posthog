import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { EventsNode } from '~/queries/schema/schema-general'
import { BaseMathType, HogQLMathType, IntervalType, PropertyMathType } from '~/types'

import { formatLLMCost, formatLLMLatency } from '../utils'

const count = (value: number): string => humanFriendlyNumber(value)

export type MetricChartKey = 'traces' | 'users' | 'cost' | 'latency' | 'errors' | 'tokens'

export interface MetricChartDefinition {
    label: string
    series: Pick<EventsNode, 'math' | 'math_property' | 'math_hogql'>
    format: (value: number) => string
}

export const METRIC_CHART_DEFINITIONS: Record<MetricChartKey, MetricChartDefinition> = {
    traces: {
        label: 'Traces',
        series: { math: HogQLMathType.HogQL, math_hogql: 'count(DISTINCT properties.$ai_trace_id)' },
        format: count,
    },
    users: {
        label: 'Users',
        series: { math: BaseMathType.UniqueUsers },
        format: count,
    },
    cost: {
        label: 'Cost',
        series: { math: PropertyMathType.Sum, math_property: '$ai_total_cost_usd' },
        format: formatLLMCost,
    },
    latency: {
        label: 'Avg. latency',
        series: { math: PropertyMathType.Average, math_property: '$ai_latency' },
        format: (value) => formatLLMLatency(value),
    },
    errors: {
        label: 'Errors',
        series: {
            math: HogQLMathType.HogQL,
            math_hogql: "countIf(notEmpty(toString(properties.$ai_error)) OR properties.$ai_is_error = 'true')",
        },
        format: count,
    },
    tokens: {
        label: 'Tokens',
        series: {
            math: HogQLMathType.HogQL,
            math_hogql: 'sum(toFloat(properties.$ai_input_tokens)) + sum(toFloat(properties.$ai_output_tokens))',
        },
        format: count,
    },
}

/** Bucket size for a date range. Short ranges get finer buckets than the app default so a spike isn't averaged away. */
export function metricChartInterval(dateFrom: string | null, dateTo: string | null): IntervalType {
    const from = dateStringToDayJs(dateFrom)
    const to = dateStringToDayJs(dateTo) ?? dayjs()
    if (from && to.diff(from, 'minute') <= 60) {
        return 'minute'
    }
    if (from && to.diff(from, 'hour') <= 4 * 24) {
        return 'hour'
    }
    return getDefaultInterval(dateFrom, dateTo)
}

export function metricChartBucketRange(
    startLabel: string,
    endLabel: string,
    interval: IntervalType
): { dateFrom: string; dateTo: string } {
    // Labels are naive project-timezone times; parsing them as UTC avoids local DST shifts.
    const format = 'YYYY-MM-DDTHH:mm:ss'
    return {
        dateFrom: dayjs.utc(startLabel).format(format),
        dateTo: dayjs.utc(endLabel).add(1, interval).subtract(1, 'second').format(format),
    }
}
