import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { IntervalType } from '~/types'

import { formatLLMCost, formatLLMLatency } from '../utils'

const count = (value: number): string => humanFriendlyNumber(value)

// Each metric reads the same events as the table column it mirrors.
const TRACE_EVENTS =
    "event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')"
const COST_EVENTS = "event IN ('$ai_generation', '$ai_embedding')"
const GENERATION_EVENTS = "event = '$ai_generation'"

export const TRACE_COUNT = 'countDistinctIf(properties.$ai_trace_id, notEmpty(toString(properties.$ai_trace_id)))'

export type MetricChartKey = 'traces' | 'users' | 'cost' | 'latency' | 'errors'

export interface MetricChartDefinition {
    label: string
    events: string
    /** HogQL aggregate over the metric's events in one bucket. */
    value: string
    format: (value: number) => string
}

export const METRIC_CHART_DEFINITIONS: Record<MetricChartKey, MetricChartDefinition> = {
    traces: { label: 'Traces', events: TRACE_EVENTS, value: TRACE_COUNT, format: count },
    users: { label: 'Users', events: GENERATION_EVENTS, value: 'count(DISTINCT distinct_id)', format: count },
    cost: {
        label: 'Cost',
        events: COST_EVENTS,
        value: 'sum(toFloat(properties.$ai_total_cost_usd))',
        format: formatLLMCost,
    },
    latency: {
        label: 'Avg. latency',
        events: GENERATION_EVENTS,
        value: 'avg(toFloat(properties.$ai_latency))',
        format: (value) => formatLLMLatency(value),
    },
    errors: {
        label: 'Errors',
        events: TRACE_EVENTS,
        value: "countIf(notEmpty(toString(properties.$ai_error)) OR properties.$ai_is_error = 'true')",
        format: count,
    },
}

/**
 * The events behind a metric, scoped like the table under the chart. With `wholeTraces`, a property filter
 * keeps every event of a trace that has one matching event, as the traces table does.
 */
export function metricChartWhere(metric: MetricChartKey, wholeTraces: boolean): string {
    const scope = wholeTraces
        ? `timestamp >= {filters.dateRange.from} AND timestamp < {filters.dateRange.to}
            AND properties.$ai_trace_id IN (SELECT properties.$ai_trace_id FROM events WHERE ${TRACE_EVENTS} AND {filters})`
        : '{filters}'
    return `${METRIC_CHART_DEFINITIONS[metric].events} AND ${scope}`
}

/** HogQL that rounds a time down to its bucket, and the step between buckets. */
export function metricChartBucket(
    interval: IntervalType,
    weekStartDay: number
): { start: (time: string) => string; step: string } {
    const unit = interval.charAt(0).toUpperCase() + interval.slice(1)
    return {
        // Week and month starts are dates; filling empty buckets needs the same type as its datetime bounds.
        start: (time) =>
            `toDateTime(${interval === 'week' ? `toStartOfWeek(${time}, ${weekStartDay})` : `toStartOf${unit}(${time})`})`,
        step: `toInterval${unit}(1)`,
    }
}

/** Bucket size for a date range. Short ranges get finer buckets than the app default so a spike isn't averaged away. */
export function metricChartInterval(dateFrom: string | null, dateTo: string | null): IntervalType {
    const from = dateStringToDayJs(dateFrom)
    // A date-only end date covers its whole day, as in the tables.
    const to =
        dateStringToDayJs(dateTo && /^\d{4}-\d{2}-\d{2}$/.test(dateTo) ? `${dateTo}T23:59:59` : dateTo) ?? dayjs()
    if (from && to.diff(from, 'minute') <= 60) {
        return 'minute'
    }
    if (from && to.diff(from, 'hour') <= 4 * 24) {
        return 'hour'
    }
    return getDefaultInterval(dateFrom, dateTo)
}

/** From the start of the first bucket to the start of the bucket after the last, which the range excludes. */
export function metricChartBucketRange(
    startLabel: string,
    endLabel: string,
    interval: IntervalType
): { dateFrom: string; dateTo: string } {
    // Labels are naive project-timezone times; parsing them as UTC avoids local DST shifts.
    const format = 'YYYY-MM-DDTHH:mm:ss'
    return {
        dateFrom: dayjs.utc(startLabel).format(format),
        dateTo: dayjs.utc(endLabel).add(1, interval).format(format),
    }
}
