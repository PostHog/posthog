import * as d3 from 'd3'

import type { ResolvedSeries, Series } from './types'

/** Translucent variant of a series colour (any CSS color form d3 can parse — hex 3/6 digit,
 *  rgb/rgba, named, HSL). Falls back to the raw string when `d3.color` returns `null`. */
export function dimColor(color: string, alpha: number): string {
    return d3.color(color)?.copy({ opacity: alpha }).toString() ?? color
}

/** Fill color for the bar at `index`: `barColors[index]` when set, else the series color. The one
 *  resolver every bar color-read site (fill, hover highlight, tooltip swatch, value labels) should
 *  use, so a per-bar series can't accidentally render bars in the series-level color. */
export function barColorAt(series: ResolvedSeries, index: number): string
export function barColorAt(series: Pick<Series, 'color' | 'barColors'>, index: number): string | undefined
export function barColorAt(series: Pick<Series, 'color' | 'barColors'>, index: number): string | undefined {
    return series.barColors?.[index] ?? series.color
}
