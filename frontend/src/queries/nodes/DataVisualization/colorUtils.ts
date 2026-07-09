import { hexToRGB } from 'lib/utils/colors'

/**
 * Returns a text color utility class (`text-white` / `text-black`) that stays readable on top of a
 * colored data-viz cell background (conditional formatting, heatmap). The class is chosen from the
 * background's relative luminance so it contrasts in both light and dark themes. Accepts either a
 * hex string ('#RRGGBB') or an 'rgb(r,g,b)' string.
 */
export function getContrastingTextClass(background: string): 'text-white' | 'text-black' {
    let r: number
    let g: number
    let b: number

    const rgbMatch = background.match(/rgba?\(([^)]+)\)/)
    if (rgbMatch) {
        ;[r, g, b] = rgbMatch[1].split(',').map((v) => parseInt(v.trim(), 10))
    } else {
        ;({ r, g, b } = hexToRGB(background))
    }

    // Perceived luminance (0-255). Below the midpoint, use light text; otherwise dark text.
    const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return luminance < 140 ? 'text-white' : 'text-black'
}
