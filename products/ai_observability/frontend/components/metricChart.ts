import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs, getDefaultInterval } from 'lib/utils/dateFilters'
import { escapeHogQLString } from 'lib/utils/hogql'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { IntervalType } from '~/types'

import { formatLLMCost, formatLLMLatency } from '../utils'

const count = (value: number): string => humanFriendlyNumber(value)

const TRACE_EVENTS =
    "event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')"

// Per-trace values, written as posthog/hogql_queries/ai/traces_query_runner.py writes the traces table's columns.
const TRACE_LATENCY = `round(coalesce(
    nullIf(maxIf(toFloat(properties.$ai_latency), event = '$ai_trace' AND toFloat(properties.$ai_latency) > 0), 0),
    CASE
        WHEN countIf(toFloat(properties.$ai_latency) > 0 AND event != '$ai_generation') = 0
            AND countIf(toFloat(properties.$ai_latency) > 0 AND event = '$ai_generation') > 0
        THEN sumIf(toFloat(properties.$ai_latency), event = '$ai_generation' AND toFloat(properties.$ai_latency) > 0)
        ELSE sumIf(toFloat(properties.$ai_latency),
            properties.$ai_parent_id IS NULL OR toString(properties.$ai_parent_id) = toString(properties.$ai_trace_id))
    END
), 2)`
const TRACE_PERSON =
    "ifNull(nullIf(argMinIf(distinct_id, timestamp, event = '$ai_trace'), ''), argMin(distinct_id, timestamp))"

export type MetricChartKey = 'traces' | 'users' | 'cost' | 'latency' | 'errors'

export interface MetricChartDefinition {
    label: string
    /** The traces table's value for one trace. */
    trace: string
    /** Combines the `value` of the rows in one bucket. */
    bucket: string
    format: (value: number) => string
}

export const METRIC_CHART_DEFINITIONS: Record<MetricChartKey, MetricChartDefinition> = {
    traces: { label: 'Traces', trace: '1', bucket: 'count()', format: count },
    users: { label: 'Users', trace: TRACE_PERSON, bucket: 'count(DISTINCT value)', format: count },
    cost: {
        label: 'Cost',
        trace: "sumIf(toFloat(properties.$ai_total_cost_usd), event IN ('$ai_generation', '$ai_embedding'))",
        bucket: 'sum(value)',
        format: formatLLMCost,
    },
    latency: {
        label: 'Avg. latency',
        trace: TRACE_LATENCY,
        bucket: 'avg(value)',
        format: (value) => formatLLMLatency(value),
    },
    errors: {
        label: 'Errors',
        trace: "countIf(isNotNull(properties.$ai_error) OR properties.$ai_is_error = 'true')",
        bucket: 'sum(value)',
        format: count,
    },
}

export interface MetricChartScope {
    metric: MetricChartKey
    /** Count each person's generations, as the Users table does, in place of whole traces. */
    usersTable: boolean
    /** A property filter is set, so few traces may match. */
    propertyFiltered: boolean
    interval: IntervalType
    weekStartDay: number
    dateFrom: string | null
    dateTo: string | null
}

/**
 * The rows of the table under the chart, each with the time the chart buckets it by. A traces table row is a
 * trace with a matching event in the range, totalled over all its events within 10 minutes of the range, as the
 * table does. It shows at its first event, or at the range start if it began earlier.
 */
function tableRows({ metric, usersTable, propertyFiltered, dateFrom }: MetricChartScope): string {
    if (usersTable) {
        return `SELECT properties.$ai_trace_id AS trace_id, timestamp AS first_seen, timestamp AS time, distinct_id AS value
            FROM events WHERE event = '$ai_generation' AND {filters}`
    }
    const bounded = !!dateFrom && dateFrom !== 'all'
    // Narrows to the matching traces before totalling them, so the trace ID index can skip the rest.
    const matchingTraces = propertyFiltered
        ? `AND properties.$ai_trace_id IN (SELECT properties.$ai_trace_id FROM events WHERE ${TRACE_EVENTS} AND {filters})`
        : ''
    return `SELECT
            properties.$ai_trace_id AS trace_id,
            min(timestamp) AS first_seen,
            ${bounded ? 'greatest(first_seen, {filters.dateRange.from})' : 'first_seen'} AS time,
            ${METRIC_CHART_DEFINITIONS[metric].trace} AS value
        FROM events
        WHERE ${TRACE_EVENTS} AND notEmpty(toString(properties.$ai_trace_id))
            AND timestamp >= {filters.dateRange.from} - toIntervalMinute(10)
            AND timestamp <= {filters.dateRange.to} + toIntervalMinute(10)
            ${matchingTraces}
        GROUP BY trace_id
        HAVING countIf({filters}) > 0 AND first_seen <= {filters.dateRange.to} AND max(timestamp) >= {filters.dateRange.from}`
}

function bucketStart({ interval, weekStartDay }: MetricChartScope, time: string): string {
    const unit = interval.charAt(0).toUpperCase() + interval.slice(1)
    // Week and month starts are dates; filling empty buckets needs the same type as its datetime bounds.
    return `toDateTime(${interval === 'week' ? `toStartOfWeek(toDateTime(${time}), ${weekStartDay})` : `toStartOf${unit}(toDateTime(${time}))`})`
}

// UTC instants, so the two 1 AM hours of a daylight saving change get different labels.
const label = (bucket: string): string => `formatDateTime(toTimeZone(${bucket}, 'UTC'), '%Y-%m-%dT%H:%i:%SZ')`

/** One row per bucket: its label, the metric, and how many traces it holds. */
export function metricChartQuery(scope: MetricChartScope): string {
    const { interval, dateFrom, dateTo } = scope
    const step = `toInterval${interval.charAt(0).toUpperCase() + interval.slice(1)}(1)`
    // An open range starts filling at its first row and ends now.
    const fillFrom = dateFrom && dateFrom !== 'all' ? `FROM ${bucketStart(scope, '{filters.dateRange.from}')}` : ''
    const fillTo = `toDateTime(${dateTo ? '{filters.dateRange.to}' : 'now()'})`
    return `
        SELECT ${label('bucket')} AS label, value, traces
        FROM (
            SELECT
                ${bucketStart(scope, 'time')} AS bucket,
                ${scope.usersTable ? 'count(DISTINCT value)' : METRIC_CHART_DEFINITIONS[scope.metric].bucket} AS value,
                countDistinctIf(trace_id, notEmpty(toString(trace_id))) AS traces
            FROM (${tableRows(scope)})
            GROUP BY bucket
            ORDER BY bucket WITH FILL ${fillFrom} TO ${fillTo} STEP ${step}
        )
        ORDER BY label
        LIMIT 10000
    `
}

/** The traces in one bucket; LIMIT 2 is enough to tell one from several. */
export function metricChartBucketTracesQuery(scope: MetricChartScope, bucketLabel: string): string {
    return `
        SELECT trace_id, min(first_seen) AS first_seen
        FROM (${tableRows(scope)})
        WHERE notEmpty(toString(trace_id)) AND ${label(bucketStart(scope, 'time'))} = ${escapeHogQLString(bucketLabel)}
        GROUP BY trace_id
        LIMIT 2
    `
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
