import { type MetricsQuery, type MetricsQueryClause, NodeKind } from '~/queries/schema/schema-general'

import type { MetricsTableWidgetConfig } from '../../generated/widget-configs.zod'
import type { MetricsTableColumn } from './metricsTableWidgetConfigValidation'

export type MetricsTableDrilldownChart = {
    title: string
    query: MetricsQuery & { clauses: MetricsQueryClause[] }
}

type DrilldownConfig = Pick<MetricsTableWidgetConfig, 'groupBy' | 'dateRange' | 'interval' | 'columns'>

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
const DATE_FROM_UNIT_SECONDS: Record<string, number> = { M: 60, h: 3_600, d: 86_400, w: 604_800 }

/** The requested point spacing, made coarser until the selected rows fit in the row budget of the query. */
function drilldownInterval(interval: string | null | undefined, dateFrom: string, rowCount: number): string | null {
    const match = /^-(\d+)([Mhdw])$/.exec(dateFrom)
    const start = INTERVAL_SECONDS.findIndex(([name]) => name === interval)
    if (!interval || !match || start === -1) {
        return interval ?? null
    }
    const spanSeconds = Number(match[1]) * DATE_FROM_UNIT_SECONDS[match[2]]
    const fits = INTERVAL_SECONDS.slice(start).find(
        ([, seconds]) => (Math.ceil(spanSeconds / seconds) + 1) * rowCount <= DRILLDOWN_ROW_BUDGET
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

/** One full chart per column for the selected rows. Each row is its own line, split by the table's label. */
export function buildMetricsTableDrilldownQueries(
    config: DrilldownConfig,
    keys: string[]
): MetricsTableDrilldownChart[] {
    const groupBy = config.groupBy
    if (!groupBy || keys.length === 0) {
        return []
    }
    const dateFrom = config.dateRange?.date_from ?? '-1h'
    const interval = drilldownInterval(config.interval, dateFrom, keys.length)
    return (config.columns ?? []).map((column) => ({
        title: column.label,
        query: {
            kind: NodeKind.MetricsQuery,
            dateRange: { date_from: dateFrom },
            ...(interval ? { interval } : {}),
            clauses: [columnClause(column, groupBy, keys)],
        },
    }))
}
