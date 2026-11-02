import type { DashboardControl } from 'scenes/dashboard/dashboardControls'

import { MetricsDisplayType, MetricsQuery, NodeKind } from '~/queries/schema/schema-general'

const METRICS_WIDGET_DEFAULT_DATE_FROM = '-1h'

export type MetricsWidgetPresetId = 'time_series' | 'stat' | 'table' | 'heatmap'

export type MetricsWidgetPreset = {
    id: MetricsWidgetPresetId
    label: string
    description: string
    display: MetricsDisplayType
}

/** Picker cards for the one `metrics` widget type. A preset only picks the first chart type, which the editor can change. */
export const METRICS_WIDGET_PRESETS: readonly MetricsWidgetPreset[] = [
    {
        id: 'time_series',
        label: 'Time series',
        description: 'A metric over time as a line, area or bar chart.',
        display: 'line',
    },
    {
        id: 'stat',
        label: 'Single stat',
        description: 'One big number, such as the latest value or the average.',
        display: 'stat',
    },
    {
        id: 'table',
        label: 'Table',
        description: 'One row per series, with its latest value.',
        display: 'table',
    },
    {
        id: 'heatmap',
        label: 'Heatmap',
        description: 'How a histogram metric, such as latency, is spread over time.',
        display: 'heatmap',
    },
]

export function metricsWidgetDefaultConfig(display: MetricsDisplayType): Record<string, unknown> {
    const query: MetricsQuery = {
        kind: NodeKind.MetricsQuery,
        clauses: [],
        dateRange: { date_from: METRICS_WIDGET_DEFAULT_DATE_FROM },
        ...(display !== 'line' ? { display: { type: display } } : {}),
    }
    return { query }
}

export function metricsWidgetQuery(config: Record<string, unknown>): MetricsQuery {
    const query = config.query as Partial<MetricsQuery> | undefined
    if (query?.kind !== NodeKind.MetricsQuery) {
        return { kind: NodeKind.MetricsQuery, clauses: [] }
    }
    return { ...query, kind: NodeKind.MetricsQuery, clauses: query.clauses ?? [] }
}

/** Dashboard filters that reach a metric widget: the date range, and label filters on builder queries only,
 * because PromQL and SQL text is not rewritten for them. */
export function metricsWidgetDashboardControls(config: Record<string, unknown>): DashboardControl[] {
    const { language } = metricsWidgetQuery(config)
    return language && language !== 'builder' ? ['dateRange'] : ['dateRange', 'metricLabels']
}

export function metricsWidgetDefaultTitle(config: Record<string, unknown>): string | undefined {
    const query = metricsWidgetQuery(config)
    if (query.language === 'promql') {
        return 'PromQL query'
    }
    if (query.language === 'sql') {
        return 'SQL query'
    }
    if (query.formula) {
        return query.formula
    }
    const metricNames = query.clauses.map((clause) => clause.metricName.trim()).filter(Boolean)
    return metricNames.length ? metricNames.join(', ') : undefined
}

export function metricsWidgetNeedsConfiguration(config: Record<string, unknown>): boolean {
    const query = metricsWidgetQuery(config)
    if (query.language === 'promql') {
        return !query.promql?.trim()
    }
    if (query.language === 'sql') {
        return !query.sql?.trim()
    }
    return !query.clauses.length || query.clauses.some((clause) => !clause.metricName.trim())
}
