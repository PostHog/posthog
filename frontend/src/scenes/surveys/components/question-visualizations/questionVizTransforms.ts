import { hexToRGBA } from 'lib/utils'

// Dim strength for non-highlighted bars. Stronger when a filter is actually applied (active),
// lighter when a choice is only "armed" for a follow-up click.
const ACTIVE_DIM_ALPHA = 0.22
const ARMED_DIM_ALPHA = 0.35

// Per-bar colors, shared by the rating and multiple-choice charts: non-highlighted bars are dimmed.
export function computeBarColors(
    baseColors: string[],
    labels: string[],
    highlightedLabel: string | null,
    hasActiveFilter: boolean
): string[] {
    return labels.map((label, index) => {
        const baseColor = baseColors[index]

        if (!highlightedLabel || label === highlightedLabel) {
            return baseColor
        }

        return hexToRGBA(baseColor, hasActiveFilter ? ACTIVE_DIM_ALPHA : ARMED_DIM_ALPHA)
    })
}

export function formatCountWithPercentage(value: number, total: number): string {
    const percentage = ((value / (total || 1)) * 100).toFixed(1)
    return `${value} (${percentage}%)`
}
