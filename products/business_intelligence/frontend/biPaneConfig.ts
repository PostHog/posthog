import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

export const BI_PANE_CHART_TYPES = [
    ChartDisplayType.Auto,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsAreaGraph,
]

export function getBIPaneFields(config: BIConfig): BIField[] {
    const fields = [...config.rows, ...config.columns]
    return [...new Set(config.panes?.fields ?? [])].flatMap((id) => fields.find((field) => field.id === id) ?? [])
}

export function getBIChartFields(config: BIConfig): BIField[] {
    const panes = new Set(
        BI_PANE_CHART_TYPES.includes(config.chartType) ? getBIPaneFields(config).map((field) => field.id) : []
    )
    return [...config.rows, ...config.columns].filter((field) => !panes.has(field.id))
}

export function isBIPanes(value: unknown): value is NonNullable<BIConfig['panes']> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return false
    }
    const panes = value as Record<string, unknown>
    return (
        Array.isArray(panes.fields) &&
        panes.fields.every((field) => typeof field === 'string') &&
        (panes.independentAxes == null || typeof panes.independentAxes === 'boolean') &&
        (panes.referenceLines == null || panes.referenceLines === 'pane' || panes.referenceLines === 'worksheet')
    )
}
