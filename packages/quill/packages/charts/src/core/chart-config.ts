import type { ChartConfig } from './types'

/** The standard chrome the axis-based charts render: axis lines, grid, tick marks, hover crosshair,
 *  a monotone line curve, rounded bars, and a cursor-anchored tooltip. LineChart, BarChart,
 *  ComboChart, and their TimeSeries variants layer this under a chart's `config` via
 *  `applyChartDefaults`, so a consumer opts out field by field; ScatterChart renders the same chrome
 *  from its own inline defaults. Sparkline and MetricCard build their own config that opts out of the
 *  chrome, so they stay chromeless. Still exported for hosts that build a config object directly. */
export const DEFAULT_CHART_CONFIG = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
    showGrid: true,
    barCornerRadius: 4,
    tooltip: { placement: 'cursor' },
} as const satisfies ChartConfig & { barCornerRadius: number }

function definedFields(config: object): Record<string, unknown> {
    return Object.fromEntries(Object.entries(config).filter(([, value]) => value !== undefined))
}

/** Layers `DEFAULT_CHART_CONFIG` under a chart's config: any field the consumer sets wins, an
 *  unset or explicitly `undefined` field falls back to the default, and `tooltip` merges key by key
 *  — dropping `undefined` at both levels — so setting one tooltip field never drops
 *  `placement: 'cursor'`. */
export function applyChartDefaults<T extends ChartConfig>(config?: T): T {
    const defined = definedFields(config ?? {})
    return {
        ...DEFAULT_CHART_CONFIG,
        ...defined,
        tooltip: { ...DEFAULT_CHART_CONFIG.tooltip, ...definedFields((defined.tooltip as object) ?? {}) },
    } as unknown as T
}
