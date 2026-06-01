import { color as d3Color } from 'd3-color'

/** Translucent variant of a series colour (any CSS color form d3 can parse — hex 3/6 digit,
 *  rgb/rgba, named, HSL). Falls back to the raw string when `d3Color` returns `null`. */
export function dimColor(color: string, alpha: number): string {
    return d3Color(color)?.copy({ opacity: alpha }).toString() ?? color
}
