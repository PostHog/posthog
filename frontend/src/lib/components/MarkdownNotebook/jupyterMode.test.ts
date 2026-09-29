import {
    JUPYTER_KEY_SEQUENCE_MS,
    NotebookJupyterKeyInput,
    NotebookJupyterPendingKey,
    resolveNotebookJupyterKey,
} from './jupyterMode'

const key = (value: string, overrides: Partial<NotebookJupyterKeyInput> = {}): NotebookJupyterKeyInput => ({
    key: value,
    shiftKey: false,
    altKey: false,
    metaKey: false,
    ctrlKey: false,
    inEditor: false,
    ...overrides,
})

describe('resolveNotebookJupyterKey', () => {
    test.each([
        ['Enter selects edit mode', key('Enter'), 'enter-edit-mode'],
        ['Shift+Enter runs and advances', key('Enter', { shiftKey: true }), 'run-and-advance'],
        ['Shift+Enter runs from the editor', key('Enter', { shiftKey: true, inEditor: true }), 'run-and-advance'],
        ['Cmd+Enter runs in place', key('Enter', { metaKey: true }), 'run'],
        ['Alt+Enter runs and inserts below', key('Enter', { altKey: true, inEditor: true }), 'run-and-insert-below'],
        ['Escape leaves the editor', key('Escape', { inEditor: true }), 'enter-command-mode'],
        ['A inserts above', key('a'), 'insert-above'],
        ['B inserts below', key('b'), 'insert-below'],
        ['Shift+V pastes above', key('V', { shiftKey: true }), 'paste-above'],
        ['M converts to markdown', key('m'), 'to-markdown'],
        ['K selects the cell above', key('k'), 'select-previous'],
        ['ArrowDown selects the cell below', key('ArrowDown'), 'select-next'],
        ['Cmd+Shift+Up moves the cell', key('ArrowUp', { metaKey: true, shiftKey: true }), 'move-up'],
        // Typing in the code editor must never add, delete, or convert cells.
        ['a letter typed in the editor', key('a', { inEditor: true }), null],
        ['Enter typed in the editor', key('Enter', { inEditor: true }), null],
        // The editor's own shortcuts keep their keys.
        ['Cmd+C in command mode', key('c', { metaKey: true }), null],
        ['Cmd+Z in command mode', key('z', { metaKey: true }), null],
    ])('%s', (_, input, expected) => {
        expect(resolveNotebookJupyterKey(input, null, 1000).command).toEqual(expected)
    })

    test.each([
        ['D D deletes', 'd', 'delete'],
        ['I I interrupts', 'i', 'interrupt'],
        ['0 0 restarts the kernel', '0', 'restart-kernel'],
    ])('%s only as a quick two-key sequence', (_, sequenceKey, expected) => {
        const first = resolveNotebookJupyterKey(key(sequenceKey), null, 1000)
        expect(first).toEqual({ command: null, pending: { key: sequenceKey, at: 1000 } })

        expect(resolveNotebookJupyterKey(key(sequenceKey), first.pending, 1200).command).toEqual(expected)

        const late = resolveNotebookJupyterKey(key(sequenceKey), first.pending, 1000 + JUPYTER_KEY_SEQUENCE_MS + 1)
        expect(late.command).toBeNull()

        const pendingOther: NotebookJupyterPendingKey = { key: 'x', at: 1000 }
        expect(resolveNotebookJupyterKey(key(sequenceKey), pendingOther, 1100).command).toBeNull()
    })
})
