import { color as d3Color } from 'd3-color'

import type { ResolvedSeries, Series } from './types'

/** Translucent variant of a series colour (any CSS color form d3 can parse — hex 3/6 digit,
 *  rgb/rgba, named, HSL). Falls back to the raw string when `d3.color` returns `null`. */
export function dimColor(color: string, alpha: number): string {
    return d3Color(color)?.copy({ opacity: alpha }).toString() ?? color
}

/** Fill color for the bar at `index`: the per-bar override (`bars[index].color`) when set, else the
 *  series color. The one resolver every bar color-read site (fill, hover highlight, tooltip swatch,
 *  value labels) should use, so a per-bar series can't accidentally render bars in the series color. */
export function barColorAt(series: ResolvedSeries, index: number): string
export function barColorAt(series: Pick<Series, 'color' | 'bars'>, index: number): string | undefined
export function barColorAt(series: Pick<Series, 'color' | 'bars'>, index: number): string | undefined {
    return series.bars?.[index]?.color ?? series.color
}
