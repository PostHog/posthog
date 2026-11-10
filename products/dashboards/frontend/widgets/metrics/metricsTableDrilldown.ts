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
import type { MetricsTableColumn } from './metricsTableWidgetConfigValidation'

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

export type MetricsTableDrilldownDashboardFilters = Pick<DashboardFilter, 'date_from' | 'date_to' | 'interval'>

type DrilldownConfig = Pick<MetricsTableWidgetConfig, 'groupBy' | 'dateRange' | 'interval' | 'columns'>

const DEFAULT_DATE_FROM = '-1h'
const COUNTER_FUNCTIONS = new Set(['rate', 'increase'])

function escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** An escaped regex even for one row: an `eq` value such as `/api/$tenant` reads as a dashboard variable. */
function rowFilter(groupBy: string, keys: string[]): NonNullable<MetricsQueryClause['filters']>[number] {
    return { key: groupBy, op: 'regex', value: `^(?:${keys.map(escapeRegex).join('|')})$` }
}

// The metrics query fails at 10,000 (bucket, series) rows, and each selected row is one series.
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

function spanSeconds(dateFrom: string, dateTo: string | null): number | null {
    const from = dateStringToDayJs(dateFrom)
    const to = dateTo ? dateStringToDayJs(dateTo) : dayjs()
    if (!from?.isValid() || !to?.isValid() || !to.isAfter(from)) {
        return null
    }
    return to.diff(from, 'second')
}

/** The point spacing all charts share: the requested one, or the backend's pick for the range when there is none,
 * made coarser until the selected rows fit in the row budget of the query. */
function drilldownInterval(
    interval: string | null,
    dateFrom: string,
    dateTo: string | null,
    rowCount: number
): string | null {
    const span = spanSeconds(dateFrom, dateTo)
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
            (Math.ceil(span / seconds) + 1) * rowCount <= DRILLDOWN_ROW_BUDGET
    )
    return (fits ?? INTERVAL_SECONDS[INTERVAL_SECONDS.length - 1])[0]
}

/** The clause the backend runs for a table column, so a full chart shows the same numbers as its row. */
function columnClause(column: MetricsTableColumn, groupBy: string, keys: string[]): MetricsQueryClause {
    const isCounter = COUNTER_FUNCTIONS.has(column.aggregation)
    return {
        name: 'a',
        metricName: column.metricName,
        aggregation: isCounter ? 'sum' : column.aggregation,
        ...(isCounter ? { rangeFunction: column.aggregation as 'rate' | 'increase' } : {}),
        ...(column.quantile != null ? { quantile: column.quantile } : {}),
        filters: [
            ...(column.filters ?? []).map(({ key, op, value }) => ({ key, op: op ?? 'eq', value })),
            rowFilter(groupBy, keys),
        ],
        groupBy: [{ key: groupBy }],
    }
}

/** One full chart per column for the selected rows. Each row is its own line, split by the table's label.
 * A dashboard date range or interval wins over the widget's, as it does for the insights on the dashboard. */
export function buildMetricsTableDrilldown(
    config: DrilldownConfig,
    keys: string[],
    dashboardFilters?: MetricsTableDrilldownDashboardFilters | null
): MetricsTableDrilldown {
    const hasDashboardRange = !!(dashboardFilters?.date_from || dashboardFilters?.date_to)
    const dateFrom =
        (hasDashboardRange ? dashboardFilters?.date_from : config.dateRange?.date_from) ?? DEFAULT_DATE_FROM
    const dateTo = (hasDashboardRange ? dashboardFilters?.date_to : null) ?? null
    const groupBy = config.groupBy
    if (!groupBy || keys.length === 0) {
        return { dateFrom, dateTo, interval: null, charts: [] }
    }
    const requested = dashboardFilters?.interval ? DASHBOARD_INTERVALS[dashboardFilters.interval] : config.interval
    const interval = drilldownInterval(requested ?? null, dateFrom, dateTo, keys.length)
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
                clauses: [columnClause(column, groupBy, keys)],
            },
        })),
    }
}
