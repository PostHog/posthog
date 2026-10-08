import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { escapeHogQLString } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { getBIDateField } from './biQueryFilters'

export const BI_COMPARISON_EMPTY_LABEL = '(empty)'

export function biComparisonCategory(expression: string): string {
    const empty = escapeHogQLString(BI_COMPARISON_EMPTY_LABEL)
    return `if(${expression} IS NULL, ${empty}, if(substring(toString(${expression}), 1, ${BI_COMPARISON_EMPTY_LABEL.length}) = ${empty}, concat(toString(${expression}), ' (category)'), toString(${expression})))`
}

export function decodeBIComparisonCategory(category: string): string | null {
    return category === BI_COMPARISON_EMPTY_LABEL
        ? null
        : category.startsWith(BI_COMPARISON_EMPTY_LABEL) && category.endsWith(' (category)')
          ? category.slice(0, -11)
          : category
}

export function decodeBIComparisonSeries(category: string): (string | null)[] {
    return category
        .split(' · ')
        .map((part) =>
            decodeBIComparisonCategory(
                part.replace(/\\(\\|s)/g, (_, escaped: string) => (escaped === 's' ? ' · ' : '\\'))
            )
        )
}

export function biComparisonSeries(period: string, dimensions: string[]): string {
    if (!dimensions.length) {
        return period
    }
    const category =
        dimensions.length === 1
            ? biComparisonCategory(dimensions[0])
            : `concat(${dimensions.map((dimension) => `replaceAll(replaceAll(${biComparisonCategory(dimension)}, ${escapeHogQLString('\\')}, ${escapeHogQLString('\\\\')}), ' · ', ${escapeHogQLString('\\s')})`).join(", ' · ', ")})`
    return `concat(${period}, ' · ', ${category})`
}

export function getBIComparisonDisabledReason(config: BIConfig): string | undefined {
    if (config.comparisonPeriod) {
        return 'This worksheet explores the comparison window of its reference date range'
    }
    if (!getBIDateField(config) || !config.dateRange?.date_from || config.dateRange.date_from === 'all') {
        return 'Select a date column and a bounded date range first'
    }
    if (
        ![
            ChartDisplayType.Auto,
            ChartDisplayType.ActionsTable,
            ChartDisplayType.ActionsBar,
            ChartDisplayType.ActionsStackedBar,
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.ActionsAreaGraph,
            ChartDisplayType.BoldNumber,
            ChartDisplayType.Metric,
        ].includes(config.chartType)
    ) {
        return 'Use a table, KPI, bar, line, or area chart for period comparisons'
    }
}

export function getBIComparisonDateExpression(field: BIField): string {
    const bucket =
        field.dateBucket && ['month', 'quarter', 'year'].includes(field.dateBucket)
            ? `, ${escapeHogQLString(field.dateBucket)}`
            : ''
    return `{filters.compareDate(${field.expression}${bucket})}`
}
