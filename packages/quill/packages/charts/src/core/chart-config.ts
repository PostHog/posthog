import type { ChartConfig } from './types'

/** The standard chrome the axis-based charts render: axis lines, grid, tick marks, hover crosshair,
 *  a monotone line curve, rounded bars, and a cursor-anchored tooltip. `applyChartDefaults` layers
 *  this under a chart's `config`, so the base cartesian charts (LineChart, BarChart, ComboChart,
 *  ScatterChart, and their TimeSeries variants) render it by default and a consumer opts out field
 *  by field. Sparkline and MetricCard build their own config and never call it, so they stay
 *  chromeless. Still exported for hosts that build a config object directly. */
export const DEFAULT_CHART_CONFIG = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
    showGrid: true,
    barCornerRadius: 4,
    tooltip: { placement: 'cursor' },
} as const satisfies ChartConfig & { barCornerRadius: number }

/** Layers `DEFAULT_CHART_CONFIG` under a chart's config: any field the consumer sets wins, an
 *  unset (or explicitly `undefined`) field falls back to the default, and `tooltip` merges key by
 *  key so setting one tooltip field doesn't drop `placement: 'cursor'`. */
export function applyChartDefaults<T extends ChartConfig>(config?: T): T {
    const defined = Object.fromEntries(Object.entries(config ?? {}).filter(([, value]) => value !== undefined))
    return {
        ...DEFAULT_CHART_CONFIG,
        ...defined,
        tooltip: { ...DEFAULT_CHART_CONFIG.tooltip, ...defined.tooltip },
    } as unknown as T
}
