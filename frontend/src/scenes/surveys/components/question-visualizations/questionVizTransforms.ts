import { hexToRGB } from 'lib/utils/colors'

// Share of the base color kept for non-highlighted bars. Stronger dim when a filter is actually
// applied (active), lighter when a choice is only "armed" for a follow-up click. Keeps must stay
// clearly above the bar track's ~0.14-0.32 alpha tint so dimmed bars don't melt into the track.
const ACTIVE_DIM_KEEP = 0.4
const ARMED_DIM_KEEP = 0.55

// Opaque dim: mix toward the surface (black in dark mode, white in light) instead of alpha, so
// dimmed bars stay solid over the hatched bar track rendered behind them.
function dimColor(hex: string, keep: number, isDarkModeOn: boolean): string {
    const { r, g, b } = hexToRGB(hex)
    const towards = isDarkModeOn ? 0 : 255
    const mix = (channel: number): number => Math.round(channel * keep + towards * (1 - keep))
    return `rgb(${mix(r)},${mix(g)},${mix(b)})`
}

// Per-bar colors, shared by the rating and multiple-choice charts: non-highlighted bars are dimmed.
export function computeBarColors(
    baseColors: string[],
    labels: string[],
    highlightedLabel: string | null,
    hasActiveFilter: boolean,
    isDarkModeOn: boolean
): string[] {
    return labels.map((label, index) => {
        const baseColor = baseColors[index]

        if (!highlightedLabel || label === highlightedLabel) {
            return baseColor
        }

        return dimColor(baseColor, hasActiveFilter ? ACTIVE_DIM_KEEP : ARMED_DIM_KEEP, isDarkModeOn)
    })
}

export function formatCountWithPercentage(value: number, total: number): string {
    const percentage = ((value / (total || 1)) * 100).toFixed(1)
    return `${value} (${percentage}%)`
}
