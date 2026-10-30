import { dimColor, resolveCssColor, toSrgbColor } from '../../core/color-utils'
import type { ChartTheme } from '../../core/types'
import { FONT_FAMILY } from '../../utils/text-measure'
import type { GaugeThreshold } from './gauge-layout'

/** Every color the gauge paints, as concrete values the canvas accepts, plus the host font. */
export interface GaugeColors {
    base: string
    /** Sorted like the input, each with its color resolved. */
    thresholds: GaugeThreshold[]
    track: string
    /** The host's text color, for the target tick and the track tint. */
    ink: string
    fontFamily: string
}

interface GaugeColorInput {
    sorted: readonly GaugeThreshold[]
    color: string | undefined
    trackColor: string | undefined
    theme: ChartTheme
}

const FALLBACK_COLOR = '#1d4aff'
const FALLBACK_INK = '#1f2328'
const FALLBACK_TRACK = 'rgba(128, 128, 128, 0.16)'
const TRACK_ALPHA = 0.1

const isVar = (color: string): boolean => color.trim().startsWith('var(')

/** A `var(--…)` that does not resolve would reach the canvas as an invalid color, which the canvas
 *  ignores, so it paints with whatever color the previous stroke left behind. */
function resolveColor(color: string, fallback: string, root: HTMLElement | null): string {
    let resolved = resolveCssColor(color, root ?? undefined).trim()
    // jsdom and other non-browser hosts do not inherit custom properties down to the wrapper.
    if (root && isVar(resolved)) {
        resolved = resolveCssColor(color).trim()
    }
    return resolved && !isVar(resolved) ? resolved : fallback
}

/** Colors for the first render, before the wrapper mounts. No DOM reads, so it is safe during render;
 *  nothing paints with it, because the canvas waits for its first measurement. */
export function initialGaugeColors({ sorted, color, theme }: GaugeColorInput): GaugeColors {
    const palette = theme.colors[0] || FALLBACK_COLOR
    const base = color && !isVar(color) ? color : palette
    return {
        base,
        thresholds: sorted.map((t) => (isVar(t.color) ? { ...t, color: base } : t)),
        track: theme.gridColor ?? FALLBACK_TRACK,
        ink: FALLBACK_INK,
        fontFamily: FONT_FAMILY,
    }
}

/** Resolve every color against the mounted wrapper, so a scoped theme container applies. */
export function resolveGaugeColors(
    root: HTMLElement,
    { sorted, color, trackColor, theme }: GaugeColorInput
): GaugeColors {
    const palette = theme.colors[0] || FALLBACK_COLOR
    const base = resolveColor(color || palette, palette, root)
    const style = getComputedStyle(root)
    const ink = resolveColor(style.color || FALLBACK_INK, FALLBACK_INK, root)
    let track = trackColor ? resolveColor(trackColor, FALLBACK_TRACK, root) : ''
    if (!track) {
        const srgbInk = toSrgbColor(ink)
        const tinted = dimColor(srgbInk, TRACK_ALPHA)
        track = tinted === srgbInk ? (theme.gridColor ?? FALLBACK_TRACK) : tinted
    }
    return {
        base,
        thresholds: sorted.map((t) => ({ ...t, color: resolveColor(t.color, base, root) })),
        track,
        ink,
        fontFamily: style.fontFamily || FONT_FAMILY,
    }
}
