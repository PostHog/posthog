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

function rowFilter(groupBy: string, keys: string[]): NonNullable<MetricsQueryClause['filters']>[number] {
    if (keys.length === 1) {
        return { key: groupBy, op: 'eq', value: keys[0] }
    }
    return { key: groupBy, op: 'regex', value: `^(?:${keys.map(escapeRegex).join('|')})$` }
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
    return (config.columns ?? []).map((column) => ({
        title: column.label,
        query: {
            kind: NodeKind.MetricsQuery,
            dateRange: { date_from: config.dateRange?.date_from ?? '-1h' },
            ...(config.interval ? { interval: config.interval } : {}),
            clauses: [columnClause(column, groupBy, keys)],
        },
    }))
}
