import { KeyIntent, KeyState, keyIntent } from './commandKKeys'

const NO_MODIFIERS = { metaKey: false, ctrlKey: false }
const state = (overrides: Partial<KeyState> = {}): KeyState => ({
    atStart: false,
    chipCount: 0,
    selectedChipIndex: null,
    tabHasAction: false,
    ...overrides,
})

describe('keyIntent', () => {
    test.each<[string, string, KeyState, KeyIntent | null, boolean?]>([
        ['Enter opens the highlighted row', 'Enter', state(), { type: 'activate', newTab: false }],
        ['Cmd+Enter opens in a new tab', 'Enter', state(), { type: 'activate', newTab: true }, true],
        [
            'Enter on a selected chip edits it',
            'Enter',
            state({ chipCount: 2, selectedChipIndex: 0 }),
            { type: 'edit-chip', index: 0 },
        ],
        [
            'first Backspace at the start selects the last chip',
            'Backspace',
            state({ atStart: true, chipCount: 2 }),
            { type: 'select-chip', index: 1 },
        ],
        [
            'second Backspace removes it',
            'Backspace',
            state({ atStart: true, chipCount: 2, selectedChipIndex: 1 }),
            { type: 'remove-chip', index: 1 },
        ],
        ['Backspace inside the text is left to the input', 'Backspace', state({ chipCount: 2 }), null],
        [
            'ArrowLeft at the start walks back through chips',
            'ArrowLeft',
            state({ atStart: true, chipCount: 2, selectedChipIndex: 1 }),
            { type: 'select-chip', index: 0 },
        ],
        [
            'ArrowRight past the last chip returns to the text',
            'ArrowRight',
            state({ chipCount: 2, selectedChipIndex: 1 }),
            { type: 'select-chip', index: null },
        ],
        ['ArrowRight with no chip selected is left to the input', 'ArrowRight', state({ chipCount: 2 }), null],
        ['typing is left to the input', 'a', state(), null],
        ['Tab completes or asks AI when it has an action', 'Tab', state({ tabHasAction: true }), { type: 'complete' }],
        ['Tab with nothing to do moves focus', 'Tab', state(), null],
    ])('%s', (_, key, keyState, expected, metaKey = false) => {
        expect(keyIntent(key, { ...NO_MODIFIERS, metaKey }, keyState)).toEqual(expected)
    })
})
