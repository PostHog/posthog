import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

export interface InsightDisplay {
    unit: string
    prefix: string
}

const PERCENT_FORMATS = new Set(['percentage', 'percentage_scaled'])
const UNCHARTED_DISPLAYS = new Set([
    'ActionsTable',
    'ActionsPie',
    'BoldNumber',
    'WorldMap',
    'ActionsBarValue',
    'ActionsLineGraphCumulative',
    'SlopeGraph',
])

function record(value: unknown): Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
}

function source(query: unknown): Record<string, unknown> {
    const node = record(query)
    return node.kind === 'InsightVizNode' || node.kind === 'DataVisualizationNode' ? record(node.source) : node
}

export function insightName(insight: Pick<InsightApi, 'name' | 'derived_name' | 'short_id'>): string {
    return insight.name || insight.derived_name || insight.short_id
}

export function insightIneligibleReason(insight: Pick<InsightApi, 'query'>): string | null {
    const node = record(insight.query)
    if (node.kind === 'DataVisualizationNode') {
        return null
    }
    const query = source(insight.query)
    if (query.kind !== 'TrendsQuery') {
        return 'Bets can measure trends insights only.'
    }
    const series = Array.isArray(query.series) ? query.series : []
    const trends = record(query.trendsFilter)
    const formulas = [trends.formulas, trends.formulaNodes].find((value) => Array.isArray(value) && value.length)
    const visible = trends.formula ? 1 : Array.isArray(formulas) ? formulas.length : series.length
    const breakdown = record(query.breakdownFilter)
    if (visible !== 1 || breakdown.breakdown || (Array.isArray(breakdown.breakdowns) && breakdown.breakdowns.length)) {
        return 'This insight has more than one series.'
    }
    const display = trends.display
    if (typeof display === 'string' && UNCHARTED_DISPLAYS.has(display)) {
        return 'Bets needs an insight shown as a line or bar chart.'
    }
    return null
}

export function insightDisplay(insight: Pick<InsightApi, 'query'> | null): InsightDisplay {
    const filter = record(source(insight?.query).trendsFilter)
    const postfix = typeof filter.aggregationAxisPostfix === 'string' ? filter.aggregationAxisPostfix.trim() : ''
    const prefix = typeof filter.aggregationAxisPrefix === 'string' ? filter.aggregationAxisPrefix.trim() : ''
    return { unit: postfix || (PERCENT_FORMATS.has(String(filter.aggregationAxisFormat)) ? '%' : ''), prefix }
}

export function formatMeasure(value: number, measure: InsightDisplay | null): string {
    const formatted = new Intl.NumberFormat(
        'en-US',
        Math.abs(value) < 1000 ? { maximumSignificantDigits: 4 } : { maximumFractionDigits: 0 }
    ).format(value)
    const unit = measure?.unit ?? ''
    return `${measure?.prefix ?? ''}${formatted}${unit === '%' ? '%' : unit ? ` ${unit}` : ''}`
}
