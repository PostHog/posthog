import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { EventsNode } from '~/queries/schema/schema-general'
import { HogQLMathType, IntervalType, PropertyMathType } from '~/types'

import { formatLLMCost, formatLLMLatency } from '../utils'

const count = (value: number): string => humanFriendlyNumber(value)

// Each metric reads the same events as the table column it mirrors.
export const TRACE_EVENTS =
    "event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')"
const COST_EVENTS = "event IN ('$ai_generation', '$ai_embedding')"
const GENERATION_EVENTS = "event = '$ai_generation'"

export type MetricChartKey = 'traces' | 'users' | 'cost' | 'latency' | 'errors'

export interface MetricChartDefinition {
    label: string
    eventFilter: string
    series: Pick<EventsNode, 'math' | 'math_property' | 'math_hogql'>
    format: (value: number) => string
}

export const METRIC_CHART_DEFINITIONS: Record<MetricChartKey, MetricChartDefinition> = {
    traces: {
        label: 'Traces',
        eventFilter: TRACE_EVENTS,
        series: {
            math: HogQLMathType.HogQL,
            math_hogql: 'countDistinctIf(properties.$ai_trace_id, notEmpty(toString(properties.$ai_trace_id)))',
        },
        format: count,
    },
    users: {
        label: 'Users',
        eventFilter: GENERATION_EVENTS,
        series: { math: HogQLMathType.HogQL, math_hogql: 'count(DISTINCT distinct_id)' },
        format: count,
    },
    cost: {
        label: 'Cost',
        eventFilter: COST_EVENTS,
        series: { math: PropertyMathType.Sum, math_property: '$ai_total_cost_usd' },
        format: formatLLMCost,
    },
    latency: {
        label: 'Avg. latency',
        eventFilter: GENERATION_EVENTS,
        series: { math: PropertyMathType.Average, math_property: '$ai_latency' },
        format: (value) => formatLLMLatency(value),
    },
    errors: {
        label: 'Errors',
        eventFilter: TRACE_EVENTS,
        series: {
            math: HogQLMathType.HogQL,
            math_hogql: "countIf(notEmpty(toString(properties.$ai_error)) OR properties.$ai_is_error = 'true')",
        },
        format: count,
    },
}

/** A date-only end date covers its whole day, as in the tables. Spelled out because the chart sends exact bounds. */
export function metricChartDateTo(dateTo: string | null): string | null {
    return dateTo && /^\d{4}-\d{2}-\d{2}$/.test(dateTo) ? `${dateTo}T23:59:59` : dateTo
}

/** Bucket size for a date range. Short ranges get finer buckets than the app default so a spike isn't averaged away. */
export function metricChartInterval(dateFrom: string | null, dateTo: string | null): IntervalType {
    const from = dateStringToDayJs(dateFrom)
    const to = dateStringToDayJs(metricChartDateTo(dateTo)) ?? dayjs()
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
