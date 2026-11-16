import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import {
    type DashboardFilter,
    type MetricsQuery,
    type MetricsQueryClause,
    NodeKind,
} from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import type { MetricsTableWidgetConfig } from '../../generated/widget-configs.zod'
import { type MetricsTableColumn, metricsTableGroupByLabels } from './metricsTableWidgetConfigValidation'

export type MetricsTableDrilldownChart = {
    title: string
    query: MetricsQuery & { clauses: MetricsQueryClause[] }
}

export type MetricsTableDrilldown = {
    dateFrom: string
    dateTo: string | null
    /** Shared by every chart, so their points line up. Null only when the range can't be measured. */
    interval: string | null
    charts: MetricsTableDrilldownChart[]
}

export type MetricsTableDrilldownDashboardFilters = Pick<
    DashboardFilter,
    'date_from' | 'date_to' | 'explicitDate' | 'interval'
>

type DrilldownConfig = Pick<MetricsTableWidgetConfig, 'groupBy' | 'dateRange' | 'interval' | 'columns'>
type MetricsQueryFilter = NonNullable<MetricsQueryClause['filters']>[number]

const DEFAULT_DATE_FROM = '-1h'
// The metrics query rejects spans over 31 days. A day less leaves room for time zones and daylight saving.
const MAX_SPAN_DAYS = 30
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const COUNTER_FUNCTIONS = new Set(['rate', 'increase'])

function escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** An escaped regex even for one row: an `eq` value such as `/api/$tenant` reads as a dashboard variable. */
function rowFilter(groupBy: string, keys: string[]): MetricsQueryFilter {
    return { key: groupBy, op: 'regex', value: `^(?:${keys.map(escapeRegex).join('|')})$` }
}

// The metrics query takes at most 10 clauses.
const MAX_DRILLDOWN_CLAUSES = 10

/** One filter per label, matching every value the rows have for it. */
function rowsFilters(labels: string[], rows: string[][]): MetricsQueryFilter[] {
    return labels.map((label, index) => rowFilter(label, [...new Set(rows.map((row) => row[index]))]))
}

/** Filter sets that together match exactly the selected rows, one clause each. The filters of one clause match
 * every combination of their values, so rows that differ in more than one label split into clauses that share
 * all labels but the last. Past the clause limit, one clause matches each label's values, and a few
 * unselected combinations can show. */
function drilldownFilterSets(labels: string[], rows: string[][]): MetricsQueryFilter[][] {
    const combinations = labels.reduce((count, _, index) => count * new Set(rows.map((row) => row[index])).size, 1)
    if (combinations === rows.length) {
        return [rowsFilters(labels, rows)]
    }
    const byPrefix = new Map<string, string[][]>()
    for (const row of rows) {
        const prefix = JSON.stringify(row.slice(0, -1))
        byPrefix.set(prefix, [...(byPrefix.get(prefix) ?? []), row])
    }
    if (byPrefix.size > MAX_DRILLDOWN_CLAUSES) {
        return [rowsFilters(labels, rows)]
    }
    return [...byPrefix.values()].map((group) => rowsFilters(labels, group))
}

function matchedSeriesCount(filterSets: MetricsQueryFilter[][], labels: string[], rows: string[][]): number {
    if (filterSets.length !== 1) {
        return rows.length
    }
    return labels.reduce((count, _, index) => count * new Set(rows.map((row) => row[index])).size, 1)
}

// The metrics query fails at 10,000 (bucket, series) rows, and each matched combination is one series.
const DRILLDOWN_ROW_BUDGET = 9_000
// The same numbers the backend uses: about 60 points when no interval is set, and never more than 500.
const DRILLDOWN_TARGET_BUCKETS = 60
const DRILLDOWN_MAX_BUCKETS = 500
const INTERVAL_SECONDS: [string, number][] = [
    ['minute', 60],
    ['minute_5', 300],
    ['minute_15', 900],
    ['minute_30', 1_800],
    ['hour', 3_600],
    ['hour_6', 21_600],
    ['day', 86_400],
    ['week', 604_800],
]
// A dashboard interval is an insight interval, which goes finer and coarser than a metrics query can.
const DASHBOARD_INTERVALS: Record<IntervalType, string> = {
    second: 'minute',
    minute: 'minute',
    hour: 'hour',
    day: 'day',
    week: 'week',
    month: 'week',
    quarter: 'week',
    year: 'week',
}

/** Measured in the project's timezone, where the backend resolves the same strings. */
function spanSeconds(dateFrom: string, dateTo: string | null, timezone: string): number | null {
    const from = dateStringToDayJs(dateFrom, timezone)
    const to = dateTo ? dateStringToDayJs(dateTo, timezone) : dayjs()
    if (!from?.isValid() || !to?.isValid() || !to.isAfter(from)) {
        return null
    }
    return to.diff(from, 'second')
}

/** The point spacing all charts share: the requested one, or the backend's pick for the range when there is none,
 * made coarser until the matched series fit in the row budget of the query. */
function drilldownInterval(
    interval: string | null,
    dateFrom: string,
    dateTo: string | null,
    seriesCount: number,
    timezone: string
): string | null {
    const span = spanSeconds(dateFrom, dateTo, timezone)
    if (span === null) {
        return interval
    }
    const start = interval
        ? INTERVAL_SECONDS.findIndex(([name]) => name === interval)
        : INTERVAL_SECONDS.findIndex(([, seconds]) => span / seconds <= DRILLDOWN_TARGET_BUCKETS)
    if (start === -1) {
        return interval ?? INTERVAL_SECONDS[INTERVAL_SECONDS.length - 1][0]
    }
    const fits = INTERVAL_SECONDS.slice(start).find(
        ([, seconds]) =>
            span / seconds <= DRILLDOWN_MAX_BUCKETS &&
            (Math.ceil(span / seconds) + 1) * seriesCount <= DRILLDOWN_ROW_BUDGET
    )
    return (fits ?? INTERVAL_SECONDS[INTERVAL_SECONDS.length - 1])[0]
}

/** The dashboard range as the metrics query must receive it. That query reads a date-only end as midnight, so a
 * dashboard end that means the whole day gets its last second. A range longer than the query allows keeps its end
 * and loses its start. */
function dashboardDateRange(
    filters: MetricsTableDrilldownDashboardFilters,
    timezone: string
): {
    dateFrom: string
    dateTo: string | null
} {
    const dateFrom = filters.date_from ?? DEFAULT_DATE_FROM
    let dateTo = filters.date_to ?? null
    if (dateTo && !filters.explicitDate && DATE_ONLY.test(dateTo)) {
        dateTo = `${dateTo}T23:59:59`
    }
    const span = spanSeconds(dateFrom, dateTo, timezone)
    if (span === null || span <= MAX_SPAN_DAYS * 86_400) {
        return { dateFrom, dateTo }
    }
    if (!dateTo) {
        return { dateFrom: `-${MAX_SPAN_DAYS}d`, dateTo }
    }
    const to = dateStringToDayJs(dateTo, timezone)
    return { dateFrom: to ? to.subtract(MAX_SPAN_DAYS, 'day').format('YYYY-MM-DDTHH:mm:ss') : dateFrom, dateTo }
}

/** The clause the backend runs for a table column, so a full chart shows the same numbers as its row. */
function columnClause(
    column: MetricsTableColumn,
    name: string,
    groupBy: string[],
    rowFilters: MetricsQueryFilter[]
): MetricsQueryClause {
    const isCounter = COUNTER_FUNCTIONS.has(column.aggregation)
    return {
        name,
        metricName: column.metricName,
        aggregation: isCounter ? 'sum' : column.aggregation,
        ...(isCounter ? { rangeFunction: column.aggregation as 'rate' | 'increase' } : {}),
        ...(column.quantile != null ? { quantile: column.quantile } : {}),
        filters: [
            ...(column.filters ?? []).map(({ key, op, value }) => ({ key, op: op ?? 'eq', value })),
            ...rowFilters,
        ],
        groupBy: groupBy.map((key) => ({ key })),
    }
}

/** One full chart per column for the selected rows. Each row is its own line, split by the table's labels.
 * A row is its label values, in the order of the config's group-by labels.
 * A dashboard date range or interval wins over the widget's, as it does for the insights on the dashboard. */
export function buildMetricsTableDrilldown(
    config: DrilldownConfig,
    rows: string[][],
    dashboardFilters?: MetricsTableDrilldownDashboardFilters | null,
    timezone: string = 'UTC'
): MetricsTableDrilldown {
    const { dateFrom, dateTo } =
        dashboardFilters && (dashboardFilters.date_from || dashboardFilters.date_to)
            ? dashboardDateRange(dashboardFilters, timezone)
            : { dateFrom: config.dateRange?.date_from ?? DEFAULT_DATE_FROM, dateTo: null }
    const groupBy = metricsTableGroupByLabels(config.groupBy)
    if (groupBy.length === 0 || rows.length === 0) {
        return { dateFrom, dateTo, interval: null, charts: [] }
    }
    const requested = dashboardFilters?.interval ? DASHBOARD_INTERVALS[dashboardFilters.interval] : config.interval
    const filterSets = drilldownFilterSets(groupBy, rows)
    const seriesCount = matchedSeriesCount(filterSets, groupBy, rows)
    const interval = drilldownInterval(requested ?? null, dateFrom, dateTo, seriesCount, timezone)
    const dateRange = dateTo ? { date_from: dateFrom, date_to: dateTo } : { date_from: dateFrom }
    return {
        dateFrom,
        dateTo,
        interval,
        charts: (config.columns ?? []).map((column) => ({
            title: column.label,
            query: {
                kind: NodeKind.MetricsQuery,
                dateRange,
                ...(interval ? { interval } : {}),
                clauses: filterSets.map((filters, index) =>
                    columnClause(column, String.fromCharCode(97 + index), groupBy, filters)
                ),
            },
        })),
    }
}
