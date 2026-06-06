import { hexToRGBA } from 'lib/utils'

// Dim strength for non-highlighted bars. Stronger when a filter is actually applied (active),
// lighter when a choice is only "armed" for a follow-up click.
const ACTIVE_DIM_ALPHA = 0.22
const ARMED_DIM_ALPHA = 0.35

/**
 * Per-bar colors with the non-highlighted bars dimmed. Shared by the rating and multiple-choice
 * charts: bars matching `highlightedLabel` (or all bars when nothing is highlighted) keep their
 * base color; the rest fade toward transparent.
 */
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
