import { color as d3Color, rgb as d3Rgb } from 'd3-color'

import type { ResolvedSeries, Series } from './types'

/** Translucent variant of a series colour (any CSS color form d3 can parse — hex 3/6 digit,
 *  rgb/rgba, named, HSL). Falls back to the raw string when `d3.color` returns `null`. */
export function dimColor(color: string, alpha: number): string {
    return d3Color(color)?.copy({ opacity: alpha }).toString() ?? color
}

/** Linear RGB interpolation between two colors. `t` is clamped to [0, 1]; `t=0` returns `from`,
 *  `t=1` returns `to`. Falls back to `from` when either color can't be parsed. */
export function mixColors(from: string, to: string, t: number): string {
    const a = d3Rgb(from)
    const b = d3Rgb(to)
    // d3 returns an RGBColor with NaN channels (not null) for unparseable input.
    if (Number.isNaN(a.r) || Number.isNaN(b.r)) {
        return from
    }
    const clamped = Math.max(0, Math.min(1, t))
    const lerp = (x: number, y: number): number => x + (y - x) * clamped
    return d3Rgb(lerp(a.r, b.r), lerp(a.g, b.g), lerp(a.b, b.b), lerp(a.opacity, b.opacity)).toString()
}

/** Fill color for the bar at `index`: the per-bar override (`bars[index].color`) when set, else the
 *  series color. The one resolver every bar color-read site (fill, hover highlight, tooltip swatch,
 *  value labels) should use, so a per-bar series can't accidentally render bars in the series color. */
export function barColorAt(series: ResolvedSeries, index: number): string
export function barColorAt(series: Pick<Series, 'color' | 'bars'>, index: number): string | undefined
export function barColorAt(series: Pick<Series, 'color' | 'bars'>, index: number): string | undefined {
    return series.bars?.[index]?.color ?? series.color
}
