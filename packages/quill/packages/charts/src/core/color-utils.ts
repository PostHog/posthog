import { color as d3Color, rgb as d3Rgb } from 'd3-color'

import type { ResolvedSeries, Series } from './types'

/** Translucent variant of a series colour (any CSS color form d3 can parse — hex 3/6 digit,
 *  rgb/rgba, named, HSL). Falls back to the raw string when `d3.color` returns `null`. */
export function dimColor(color: string, alpha: number): string {
    return d3Color(color)?.copy({ opacity: alpha }).toString() ?? color
}

/** Resolve a CSS custom-property reference (`var(--x)`, with an optional fallback) to its
 *  computed color value. A canvas 2D context can't resolve `var()`, so an accent handed to
 *  `fillStyle`/`strokeStyle` (or through `dimColor`, which relies on `d3.color` parsing it)
 *  must be a concrete color first. Non-`var()` inputs, and SSR/no-DOM contexts, return the
 *  input unchanged; `root` defaults to `document.body` to match {@link themeFromCssVars}. */
export function resolveCssColor(color: string, root?: HTMLElement): string {
    const trimmed = color.trim()
    if (!trimmed.startsWith('var(')) {
        return color
    }
    if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') {
        return color
    }
    const match = /^var\(\s*(--[^,)]+?)\s*(?:,\s*([\s\S]+))?\)$/.exec(trimmed)
    if (!match) {
        return color
    }
    const [, name, fallback] = match
    const el = root ?? document.body
    const value = getComputedStyle(el).getPropertyValue(name).trim()
    if (value) {
        return value
    }
    return fallback && fallback.trim() ? resolveCssColor(fallback.trim(), el) : color
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

let srgbProbe: CanvasRenderingContext2D | null | undefined

/** `color` in a form d3 can parse. Modern syntax such as `oklch()` survives a round trip through
 *  `fillStyle` unchanged, so it is painted to one pixel and read back. Returns the input when
 *  there is no DOM or the browser rejects the color. */
export function toSrgbColor(color: string): string {
    if (!Number.isNaN(d3Rgb(color).r)) {
        return color
    }
    if (srgbProbe === undefined) {
        srgbProbe =
            typeof document === 'undefined'
                ? null
                : document.createElement('canvas').getContext('2d', { willReadFrequently: true })
    }
    if (!srgbProbe) {
        return color
    }
    srgbProbe.clearRect(0, 0, 1, 1)
    srgbProbe.fillStyle = 'transparent'
    srgbProbe.fillStyle = color
    srgbProbe.fillRect(0, 0, 1, 1)
    const [r, g, b, a] = srgbProbe.getImageData(0, 0, 1, 1).data
    return a === 0 ? color : d3Rgb(r, g, b, a / 255).toString()
}

// APCA lightness of black text: 0 after the soft black clamp, raised to the text exponent.
const APCA_BLACK_TEXT = (0.022 ** 1.414) ** 0.57

/** Whether white text reads better than black over a fill, by APCA (the WCAG 3 draft contrast).
 *  A luminance cutoff or WCAG 2 picks black on mid tones such as #f14f58, where white reads
 *  better. Unparseable input returns false, so a caller falls back to dark text. */
export function prefersLightText(color: string): boolean {
    const c = d3Rgb(color)
    if (Number.isNaN(c.r)) {
        return false
    }
    const y = 0.2126729 * (c.r / 255) ** 2.4 + 0.7151522 * (c.g / 255) ** 2.4 + 0.072175 * (c.b / 255) ** 2.4
    return 1 - y ** 0.65 > y ** 0.56 - APCA_BLACK_TEXT
}

/** Fill color for the bar at `index`: the per-bar override (`bars[index].color`) when set, else the
 *  series color. The one resolver every bar color-read site (fill, hover highlight, tooltip swatch,
 *  value labels) should use, so a per-bar series can't accidentally render bars in the series color. */
export function barColorAt(series: ResolvedSeries, index: number): string
export function barColorAt(series: Pick<Series, 'color' | 'bars'>, index: number): string | undefined
export function barColorAt(series: Pick<Series, 'color' | 'bars'>, index: number): string | undefined {
    return series.bars?.[index]?.color ?? series.color
}
