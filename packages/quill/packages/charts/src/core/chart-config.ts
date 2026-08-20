import type { ChartConfig } from './types'

/** The switches a host turns on for every chart at once. Each one defaults to off so a chart owns
 *  no styling of its own — a sparkline in a table cell wants none of this — which otherwise leaves
 *  every host to decide the same thing.
 *
 *  Merge the nested `tooltip` rather than replacing it, or `placement` reverts to `follow-data`
 *  while every other chart follows the cursor. */
export const DEFAULT_CHART_CONFIG = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
    showGrid: true,
    barCornerRadius: 4,
    tooltip: { placement: 'cursor' },
} as const satisfies ChartConfig & { barCornerRadius: number }
