import { KeyIntent, KeyState, keyIntent } from './commandKKeys'

const NO_MODIFIERS = { metaKey: false, ctrlKey: false }
const state = (overrides: Partial<KeyState> = {}): KeyState => ({
    atStart: false,
    chipCount: 0,
    chipSelection: null,
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
            state({ chipCount: 2, chipSelection: 0 }),
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
            state({ atStart: true, chipCount: 2, chipSelection: 1 }),
            { type: 'remove-chip', index: 1 },
        ],
        ['Backspace inside the text is left to the input', 'Backspace', state({ chipCount: 2 }), null],
        [
            'ArrowLeft at the start walks back through chips',
            'ArrowLeft',
            state({ atStart: true, chipCount: 2, chipSelection: 1 }),
            { type: 'select-chip', index: 0 },
        ],
        [
            'ArrowRight past the last chip returns to the text',
            'ArrowRight',
            state({ chipCount: 2, chipSelection: 1 }),
            { type: 'select-chip', index: null },
        ],
        ['ArrowRight with no chip selected is left to the input', 'ArrowRight', state({ chipCount: 2 }), null],
        ['typing is left to the input', 'a', state(), null],
        [
            'Cmd+A with chips selects them with the text',
            'a',
            state({ chipCount: 2 }),
            { type: 'select-chip', index: 'all', keepDefault: true },
            true,
        ],
        ['Cmd+A without chips is left to the input', 'a', state(), null, true],
        [
            'Backspace after select-all clears chips and text',
            'Backspace',
            state({ atStart: true, chipCount: 2, chipSelection: 'all' }),
            { type: 'clear' },
        ],
        [
            'ArrowLeft after select-all collapses the selection',
            'ArrowLeft',
            state({ chipCount: 2, chipSelection: 'all' }),
            { type: 'select-chip', index: null, keepDefault: true },
        ],
        [
            'ArrowDown after select-all still moves the highlight',
            'ArrowDown',
            state({ chipSelection: 'all' }),
            { type: 'move', direction: 1 },
        ],
        ['Tab completes or asks AI when it has an action', 'Tab', state({ tabHasAction: true }), { type: 'complete' }],
        ['Tab with nothing to do moves focus', 'Tab', state(), null],
    ])('%s', (_, key, keyState, expected, metaKey = false) => {
        expect(keyIntent(key, { ...NO_MODIFIERS, metaKey }, keyState)).toEqual(expected)
    })
})
