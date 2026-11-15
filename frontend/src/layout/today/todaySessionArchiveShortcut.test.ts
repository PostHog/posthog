import { TodayArchiveShortcutEvent, isTodayArchiveShortcut } from './todaySessionArchiveShortcut'

function keydown(overrides: Partial<TodayArchiveShortcutEvent>): TodayArchiveShortcutEvent {
    return {
        key: 'A',
        metaKey: false,
        ctrlKey: false,
        shiftKey: true,
        altKey: false,
        repeat: false,
        target: document.body,
        ...overrides,
    }
}

describe('todaySessionArchiveShortcut', () => {
    it.each<[string, Partial<TodayArchiveShortcutEvent>, boolean, boolean]>([
        ['Cmd+Shift+A on a Mac', { metaKey: true }, true, true],
        ['Ctrl+Shift+A elsewhere', { ctrlKey: true }, false, true],
        ['Ctrl+Shift+A on a Mac', { ctrlKey: true }, true, false],
        ['Cmd+Shift+A elsewhere', { metaKey: true }, false, false],
        ['Cmd+A without Shift', { metaKey: true, shiftKey: false, key: 'a' }, true, false],
        ['Cmd+Shift+Alt+A', { metaKey: true, altKey: true }, true, false],
        ['a held key', { metaKey: true, repeat: true }, true, false],
        ['typing in an input', { metaKey: true, target: document.createElement('input') }, true, false],
        ['typing in a textarea', { metaKey: true, target: document.createElement('textarea') }, true, false],
    ])('%s', (_, overrides, mac, expected) => {
        expect(isTodayArchiveShortcut(keydown(overrides), mac)).toBe(expected)
    })
})
