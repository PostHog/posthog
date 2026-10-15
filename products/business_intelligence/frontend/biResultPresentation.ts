import { formatDataWithSettings } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { ChartAxis, ChartSettings } from '~/queries/schema/schema-general'

import { getBIResultMeasureColumns, getBIValuePillLabel } from './biEditorTypes'
import { getBIMeasureSettings } from './biMeasureSettings'

export function getBIResultMeasures(
    config: BIConfig,
    settings?: ChartSettings
): { column: string; label: string; settings: ChartAxis['settings'] }[] {
    return getBIResultMeasureColumns(config).map(({ column, value }) => ({
        column,
        label: value?.display?.label || (value ? getBIValuePillLabel(value) : 'Count'),
        settings:
            settings?.yAxis?.find((axis) => axis.column === column)?.settings ??
            (value ? getBIMeasureSettings(value) : undefined),
    }))
}

export function biNumericValue(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
        return null
    }
    const number = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
    return Number.isFinite(number) ? number : null
}

export function formatBIMeasure(value: unknown, settings?: ChartAxis['settings']): string {
    const number = biNumericValue(value)
    return number === null
        ? '—'
        : String(formatDataWithSettings(number * (settings?.formatting?.style === 'percent' ? 100 : 1), settings))
}
