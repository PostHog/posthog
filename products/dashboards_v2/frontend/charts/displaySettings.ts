import type { MetricsDisplaySettings, MetricsDisplayType, MetricsReducer } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type { Panel } from '../spec'

const UNIT_ALIASES: Record<string, string> = {
    percent: '%',
    percentunit: '1',
    bytes: 'By',
    reqps: '1/s',
    ops: '1/s',
}
const REDUCERS: MetricsReducer[] = ['last', 'mean', 'min', 'max', 'sum']

export function unitOf(panel: Panel): string | undefined {
    const unit = panel.fieldConfig?.unit
    return unit ? (UNIT_ALIASES[unit] ?? unit) : undefined
}

function displayTypeOf(panel: Panel): MetricsDisplayType {
    const options = panel.viz.options ?? {}
    switch (panel.viz.type) {
        case 'stat':
        case 'gauge':
        case 'table':
            return panel.viz.type
        default:
            return options.style === 'bars' ? 'bar' : options.area ? 'area' : 'line'
    }
}

export function sqlDisplayOf(panel: Panel): ChartDisplayType {
    const options = panel.viz.options ?? {}
    if (panel.viz.type === 'pie') {
        return options.donut === false ? ChartDisplayType.ActionsPie : ChartDisplayType.ActionsDonut
    }
    if (panel.viz.type === 'bar' || options.style === 'bars') {
        return options.stack ? ChartDisplayType.ActionsStackedBar : ChartDisplayType.ActionsBar
    }
    return options.area ? ChartDisplayType.ActionsAreaGraph : ChartDisplayType.ActionsLineGraph
}

export function metricsDisplayOf(panel: Panel): MetricsDisplaySettings {
    const options = panel.viz.options ?? {}
    const fieldConfig = panel.fieldConfig
    const reduce = REDUCERS.find((reducer) => reducer === options.reduce)
    return {
        type: displayTypeOf(panel),
        unit: unitOf(panel),
        reduce,
        statSparkline: options.sparkline !== false,
        thresholds: fieldConfig?.thresholds?.map(({ value, color }) => ({ value, color })),
        yAxis:
            fieldConfig?.min !== undefined || fieldConfig?.max !== undefined
                ? { min: fieldConfig.min, max: fieldConfig.max }
                : undefined,
    }
}
