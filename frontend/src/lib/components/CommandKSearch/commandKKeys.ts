export type KeyIntent =
    | { type: 'move'; direction: 1 | -1 }
    | { type: 'activate'; newTab: boolean }
    | { type: 'complete' }
    | { type: 'select-chip'; index: number | null }
    | { type: 'remove-chip'; index: number }
    | { type: 'edit-chip'; index: number }
    | { type: 'clear-or-close' }

export interface KeyState {
    /** The caret sits at the very start of the text with nothing selected. */
    atStart: boolean
    chipCount: number
    selectedChipIndex: number | null
    /** Tab completes a filter row or asks AI. With neither, it moves focus as usual. */
    tabHasAction: boolean
}

/** What a key press does in the search input, or null to let the input handle it. */
export function keyIntent(
    key: string,
    modifiers: { metaKey: boolean; ctrlKey: boolean },
    state: KeyState
): KeyIntent | null {
    const { atStart, chipCount, selectedChipIndex } = state
    const chipsBeforeCaret = chipCount > 0 && atStart
    switch (key) {
        case 'ArrowDown':
            return { type: 'move', direction: 1 }
        case 'ArrowUp':
            return { type: 'move', direction: -1 }
        case 'Enter':
            return selectedChipIndex !== null
                ? { type: 'edit-chip', index: selectedChipIndex }
                : { type: 'activate', newTab: modifiers.metaKey || modifiers.ctrlKey }
        case 'Tab':
            return state.tabHasAction ? { type: 'complete' } : null
        case 'Escape':
            return { type: 'clear-or-close' }
        case 'Backspace':
            if (!chipsBeforeCaret) {
                return null
            }
            return selectedChipIndex === null
                ? { type: 'select-chip', index: chipCount - 1 }
                : { type: 'remove-chip', index: selectedChipIndex }
        case 'ArrowLeft':
            if (!chipsBeforeCaret) {
                return null
            }
            return {
                type: 'select-chip',
                index: selectedChipIndex === null ? chipCount - 1 : Math.max(0, selectedChipIndex - 1),
            }
        case 'ArrowRight':
            if (selectedChipIndex === null) {
                return null
            }
            return { type: 'select-chip', index: selectedChipIndex + 1 < chipCount ? selectedChipIndex + 1 : null }
        default:
            return null
    }
}
