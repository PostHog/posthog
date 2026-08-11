import type { ChartConfig } from './types'

/**
 * Quill's chart chrome, config side — the switches a host turns on for every chart at once.
 *
 * The individual options default to off so a chart owns no house style (a sparkline in a table cell
 * wants none of this). That leaves each host to decide the same thing, and the app previously kept
 * its own copy of exactly this object. Spread it instead, so one look reaches the app, MCP apps, the
 * desktop app, canvases, and Storybook alike:
 *
 * ```tsx
 * const config = { ...QUILL_CHART_CHROME, yAxis: { format: 'currency' } }
 * ```
 *
 * `tooltip` is nested, so a host setting any tooltip field of its own must merge rather than replace
 * this one — otherwise `placement` goes back to `follow-data` while every other chart follows the
 * cursor. Pair with {@link themeFromCssVars}, which carries the matching theme side (dashed grid,
 * axis-line color).
 */
export const QUILL_CHART_CHROME = {
    curve: 'monotone',
    showAxisLines: true,
    showTickMarks: true,
    showCrosshair: true,
    showGrid: true,
    barCornerRadius: 4,
    tooltip: { placement: 'cursor' },
} as const satisfies ChartConfig & { barCornerRadius: number }
