/** A chip index, every chip plus the text (⌘A), or nothing. */
export type ChipSelection = number | 'all' | null

export type KeyIntent =
    | { type: 'move'; direction: 1 | -1 }
    | { type: 'activate'; newTab: boolean }
    | { type: 'complete' }
    /** `keepDefault` lets the input also select or collapse its own text. */
    | { type: 'select-chip'; index: ChipSelection; keepDefault?: true }
    | { type: 'remove-chip'; index: number }
    | { type: 'edit-chip'; index: number }
    | { type: 'clear' }
    | { type: 'clear-or-close' }

export interface KeyState {
    /** The caret sits at the very start of the text with nothing selected. */
    atStart: boolean
    chipCount: number
    chipSelection: ChipSelection
    /** Tab completes a filter row or asks AI. With neither, it moves focus as usual. */
    tabHasAction: boolean
}

/** What a key press does in the search input, or null to let the input handle it. */
export function keyIntent(
    key: string,
    modifiers: { metaKey: boolean; ctrlKey: boolean },
    state: KeyState
): KeyIntent | null {
    const { atStart, chipCount, chipSelection } = state
    const chipsBeforeCaret = chipCount > 0 && atStart
    const chipIndex = typeof chipSelection === 'number' ? chipSelection : null
    switch (key) {
        case 'a':
        case 'A':
            if (!modifiers.metaKey && !modifiers.ctrlKey) {
                return null
            }
            // With no chips the input's own select-all already covers the whole query.
            return chipCount > 0 ? { type: 'select-chip', index: 'all', keepDefault: true } : null
        case 'ArrowDown':
            return { type: 'move', direction: 1 }
        case 'ArrowUp':
            return { type: 'move', direction: -1 }
        case 'Enter':
            return chipIndex !== null
                ? { type: 'edit-chip', index: chipIndex }
                : { type: 'activate', newTab: modifiers.metaKey || modifiers.ctrlKey }
        case 'Tab':
            return state.tabHasAction ? { type: 'complete' } : null
        case 'Escape':
            return { type: 'clear-or-close' }
        case 'Delete':
            return chipSelection === 'all' ? { type: 'clear' } : null
        case 'Backspace':
            if (chipSelection === 'all') {
                return { type: 'clear' }
            }
            if (!chipsBeforeCaret) {
                return null
            }
            return chipIndex === null
                ? { type: 'select-chip', index: chipCount - 1 }
                : { type: 'remove-chip', index: chipIndex }
        case 'Home':
        case 'End':
            return chipSelection === 'all' ? { type: 'select-chip', index: null, keepDefault: true } : null
        case 'ArrowLeft':
            if (chipSelection === 'all') {
                return { type: 'select-chip', index: null, keepDefault: true }
            }
            if (!chipsBeforeCaret) {
                return null
            }
            return {
                type: 'select-chip',
                index: chipIndex === null ? chipCount - 1 : Math.max(0, chipIndex - 1),
            }
        case 'ArrowRight':
            if (chipSelection === 'all') {
                return { type: 'select-chip', index: null, keepDefault: true }
            }
            if (chipIndex === null) {
                return null
            }
            return { type: 'select-chip', index: chipIndex + 1 < chipCount ? chipIndex + 1 : null }
        default:
            return null
    }
}
