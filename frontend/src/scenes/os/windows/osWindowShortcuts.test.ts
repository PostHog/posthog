import { OsWindowShortcutEvent, osWindowCommandFor } from './osWindowShortcuts'

function keyEvent(overrides: Partial<OsWindowShortcutEvent>): OsWindowShortcutEvent {
    return {
        code: 'ArrowLeft',
        altKey: true,
        shiftKey: true,
        ctrlKey: false,
        metaKey: false,
        repeat: false,
        isComposing: false,
        target: document.body,
        ...overrides,
    }
}

describe('osWindowCommandFor', () => {
    test.each([
        ['Alt+Shift+Left snaps left', { code: 'ArrowLeft' }, 'snap-left'],
        ['Alt+Shift+Right snaps right', { code: 'ArrowRight' }, 'snap-right'],
        ['Alt+Shift+Up maximizes', { code: 'ArrowUp' }, 'toggle-maximize'],
        ['Alt+Shift+Down minimizes', { code: 'ArrowDown' }, 'minimize'],
        ['Alt+Shift+W closes', { code: 'KeyW' }, 'close'],
        ['Alt+Shift+G tidies up', { code: 'KeyG' }, 'tidy-up'],
        ['a bare arrow key does nothing', { altKey: false, shiftKey: false }, null],
        ['Shift+Left alone does nothing, it selects text', { altKey: false }, null],
        ['Alt+Left alone does nothing, it is browser back', { shiftKey: false }, null],
        ['an extra Ctrl does nothing', { ctrlKey: true }, null],
        ['an extra Cmd does nothing', { metaKey: true }, null],
        ['a held key does not repeat the command', { repeat: true }, null],
        ['typing in a field does nothing', { target: document.createElement('input') }, null],
        ['composing text with an input method does nothing', { isComposing: true }, null],
        [
            'typing in a field inside a shadow root does nothing',
            { target: document.createElement('div'), composedPath: () => [document.createElement('textarea')] },
            null,
        ],
    ])('%s', (_description, overrides, expected) => {
        expect(osWindowCommandFor(keyEvent(overrides))).toEqual(expected)
    })
})
