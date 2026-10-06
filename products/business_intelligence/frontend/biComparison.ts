import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { escapeHogQLString } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import { getBIDateField } from './biQueryFilters'

export function getBIComparisonDisabledReason(config: BIConfig): string | undefined {
    if (!getBIDateField(config) || !config.dateRange?.date_from || config.dateRange.date_from === 'all') {
        return 'Select a date column and a bounded date range first'
    }
    if (config.rows.length + config.columns.length > 2) {
        return 'Period comparisons support up to two dimensions'
    }
    if (
        ![
            ChartDisplayType.Auto,
            ChartDisplayType.ActionsTable,
            ChartDisplayType.ActionsBar,
            ChartDisplayType.ActionsStackedBar,
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.ActionsAreaGraph,
        ].includes(config.chartType)
    ) {
        return 'Use a table, bar, line, or area chart for period comparisons'
    }
}

export function getBIComparisonDateExpression(field: BIField): string {
    const bucket =
        field.dateBucket && ['month', 'quarter', 'year'].includes(field.dateBucket)
            ? `, ${escapeHogQLString(field.dateBucket)}`
            : ''
    return `{filters.compareDate(${field.expression}${bucket})}`
}
