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

/**
 * Next rating filter value after clicking a bar. Clicking the already-filtered rating clears the
 * filter; clicking any other rating switches to it. Returns the value to upsert (`null` clears).
 */
export function resolveRatingClick(activeRatingLabel: string | null, clickedRatingLabel: string): string | null {
    return activeRatingLabel === clickedRatingLabel ? null : clickedRatingLabel
}

export interface ChoiceClickResult {
    /** Value to pass to the filter upsert, or `null` to leave the filters untouched. */
    upsert: { value: string | null } | null
    /** The choice that should be "armed" for a follow-up click, or `null` to disarm. */
    nextArmed: string | null
}

/**
 * Multiple-choice click state machine. Filtering takes two clicks (arm, then confirm) when no
 * filter is active yet, but switches in a single click once a filter is already applied:
 *   - clicking the active choice clears the filter
 *   - clicking another choice while one is active switches to it
 *   - clicking the armed choice confirms and applies it
 *   - clicking a fresh choice arms it (no filter change yet)
 */
export function resolveChoiceClick(
    activeChoiceLabel: string | null,
    armedChoiceLabel: string | null,
    clickedChoiceLabel: string
): ChoiceClickResult {
    if (activeChoiceLabel === clickedChoiceLabel) {
        return { upsert: { value: null }, nextArmed: null }
    }

    if (activeChoiceLabel && activeChoiceLabel !== clickedChoiceLabel) {
        return { upsert: { value: clickedChoiceLabel }, nextArmed: null }
    }

    if (armedChoiceLabel === clickedChoiceLabel) {
        return { upsert: { value: clickedChoiceLabel }, nextArmed: null }
    }

    return { upsert: null, nextArmed: clickedChoiceLabel }
}
