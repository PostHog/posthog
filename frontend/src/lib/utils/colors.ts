import { tagColors } from 'lib/colors'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { hashCodeForString } from 'lib/utils/strings'

export function colorForString(s: string): LemonTagType {
    /*
    Returns a color name for a given string, where the color will always be the same for the same string.
    */
    return tagColors[hashCodeForString(s) % tagColors.length]
}

export function hexToRGB(hex: string): { r: number; g: number; b: number; a: number } {
    // Remove the "#" if it exists
    hex = hex.replace(/^#/, '')

    // Handle shorthand notation (e.g., "#123" => "#112233")
    if (hex.length === 3 || hex.length === 4) {
        hex = hex
            .split('')
            .map((char) => char + char)
            .join('')
    }

    if (hex.length !== 6 && hex.length !== 8) {
        console.warn(`Incorrectly formatted color string: ${hex}.`)
        return { r: 0, g: 0, b: 0, a: 0 }
    }

    // Extract the rgb values
    const r = parseInt(hex.slice(0, 2), 16)
    const g = parseInt(hex.slice(2, 4), 16)
    const b = parseInt(hex.slice(4, 6), 16)
    const a = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : 1

    return { r, g, b, a }
}

export function hexToRGBA(hex: string, alpha = 1): string {
    /**
     * Returns an RGBA string with specified alpha if the hex string is valid.
     * @param hex e.g. '#FF0000'
     * @param alpha e.g. 0.5
     */

    const { r, g, b } = hexToRGB(hex)
    const a = alpha
    return `rgba(${[r, g, b, a].join(',')})`
}

export function RGBToHex(rgb: string): string {
    const rgbValues = rgb.replace('rgb(', '').replace(')', '').split(',').map(Number)

    return `#${rgbValues.map((val) => val.toString(16).padStart(2, '0')).join('')}`
}

export function RGBToRGBA(rgb: string, a: number): string {
    const [r, g, b] = rgb.slice(4, rgb.length - 1).split(',')
    return `rgba(${[r, g, b, a].join(',')})`
}

/**
 * Strip any alpha channel and return an opaque `#rrggbb` hex string.
 * Accepts `rgb(...)`, `rgba(...)`, and 8-digit `#rrggbbaa` hex; opaque hex,
 * `var(--…)`, or anything unparseable is returned unchanged. Dimming a series
 * color only changes its alpha, so this losslessly recovers the opaque color.
 */
export function toOpaqueHex(color: string): string {
    const toHex = (r: number, g: number, b: number): string =>
        `#${[r, g, b]
            .map((c) =>
                Math.max(0, Math.min(255, Math.round(c)))
                    .toString(16)
                    .padStart(2, '0')
            )
            .join('')}`

    const rgbMatch = color.match(/^rgba?\(([^)]+)\)$/i)
    if (rgbMatch) {
        const channels = rgbMatch[1]
            .split(',')
            .slice(0, 3)
            .map((part) => parseFloat(part.trim()))
        if (channels.length < 3 || channels.some((c) => !Number.isFinite(c))) {
            return color
        }
        return toHex(channels[0], channels[1], channels[2])
    }
    if (/^#[0-9a-f]{8}$/i.test(color)) {
        return color.slice(0, 7)
    }
    return color
}

export function RGBToHSL(r: number, g: number, b: number): { h: number; s: number; l: number } {
    // Convert RGB values to the range 0-1
    r /= 255
    g /= 255
    b /= 255

    // Find min and max values of r, g, b
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    const delta = max - min

    // Calculate lightness
    let h = 0,
        s = 0
    const l = (max + min) / 2

    if (delta !== 0) {
        // Calculate saturation
        s = l < 0.5 ? delta / (max + min) : delta / (2 - max - min)

        // Calculate hue
        switch (max) {
            case r:
                h = ((g - b) / delta + (g < b ? 6 : 0)) % 6
                break
            case g:
                h = (b - r) / delta + 2
                break
            case b:
                h = (r - g) / delta + 4
                break
        }
        h *= 60 // Convert hue to degrees
    }

    return {
        h: Math.round(h),
        s: Math.round(s * 100),
        l: Math.round(l * 100),
    }
}

export function lightenDarkenColor(hex: string, pct: number): string {
    /**
     * Returns a lightened or darkened color, similar to SCSS darken()
     * @param hex e.g. '#FF0000'
     * @param pct percentage amount to lighten or darken, e.g. -20
     */

    function output(val: number): number {
        return Math.max(0, Math.min(255, val))
    }

    const amt = Math.round(2.55 * pct)
    let { r, g, b } = hexToRGB(hex)

    r = output(r + amt)
    g = output(g + amt)
    b = output(b + amt)

    return `rgb(${[r, g, b].join(',')})`
}

/**
 * Gradate color saturation based on its intended strength.
 * This is for visualizations where a data point's color depends on its value.
 * @param color A HEX color to gradate.
 * @param strength The strength of the data point.
 * @param floor The minimum saturation. This preserves proportionality of strength, so doesn't just cut it off.
 */
export function gradateColor(
    color: string,
    strength: number,
    floor: number = 0
): `hsla(${number}, ${number}%, ${number}%, ${string})` {
    const { r, g, b } = hexToRGB(color)
    const { h, s, l } = RGBToHSL(r, g, b)

    const saturation = floor + (1 - floor) * strength
    return `hsla(${h}, ${s}%, ${l}%, ${saturation.toPrecision(3)})`
}
