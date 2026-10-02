import { VimMode } from 'monaco-vim'

import { createNonrecursiveVimMapping } from './vimrcMappings'

jest.mock('monaco-editor', () => ({ KeyCode: {}, editor: {}, SelectionDirection: {} }))

interface Cursor {
    line: number
    ch: number
}

const Vim = (
    VimMode as unknown as {
        Vim: {
            mapclear: () => void
            handleKey: (cm: unknown, key: string) => void
            maybeInitVimState_: (cm: unknown) => void
        }
    }
).Vim

function createAdapter(): {
    state: { vim: { insertMode: boolean } | undefined }
    curOp: Record<string, unknown>
    operation: (callback: () => unknown) => unknown
    dispatch: () => void
    getCursor: () => Cursor
    setCursor: (line: number, ch: number) => void
    firstLine: () => number
    lastLine: () => number
    getLine: () => string
    findPosV: (position: Cursor, amount: number) => Cursor
    charCoords: () => { left: number }
    listSelections: () => { head: Cursor; anchor: Cursor }[]
    replaceRange: () => void
    getInputField: () => HTMLInputElement
    off: () => void
    setOption: () => void
    toggleOverwrite: () => void
    enterVimMode: () => void
} {
    let cursor = { line: 1, ch: 2 }
    const input = document.createElement('input')
    const cm = {
        state: { vim: undefined as { insertMode: boolean } | undefined },
        curOp: {},
        operation: (callback: () => unknown): unknown => callback(),
        dispatch: (): void => {},
        getCursor: (): Cursor => cursor,
        setCursor: (line: number, ch: number): void => {
            cursor = { line, ch }
        },
        firstLine: (): number => 0,
        lastLine: (): number => 2,
        getLine: (): string => 'SELECT 1',
        findPosV: (position: Cursor, amount: number): Cursor => ({ ...position, line: position.line + amount }),
        charCoords: (): { left: number } => ({ left: 0 }),
        listSelections: (): { head: Cursor; anchor: Cursor }[] => [{ head: cursor, anchor: cursor }],
        replaceRange: (): void => {},
        getInputField: (): HTMLInputElement => input,
        off: (): void => {},
        setOption: (): void => {},
        toggleOverwrite: (): void => {},
        enterVimMode: (): void => {},
    }
    Vim.maybeInitVimState_(cm)
    return cm
}

describe('createNonrecursiveVimMapping', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        Vim.mapclear()
    })

    afterEach(() => {
        Vim.mapclear()
        jest.useRealTimers()
    })

    it('swaps movement keys without recursively applying the other mapping', () => {
        const cm = createAdapter()
        createNonrecursiveVimMapping('j', 'k', 'normal')
        createNonrecursiveVimMapping('k', 'j', 'normal')

        Vim.handleKey(cm, 'j')
        expect(cm.getCursor().line).toBe(0)

        Vim.handleKey(cm, 'k')
        expect(cm.getCursor().line).toBe(1)
    })

    it('keeps the insert-mode escape mapping', () => {
        const cm = createAdapter()
        cm.state.vim!.insertMode = true
        createNonrecursiveVimMapping('jj', '<Esc>', 'insert')

        Vim.handleKey(cm, 'j')
        Vim.handleKey(cm, 'j')

        expect(cm.state.vim!.insertMode).toBe(false)
    })

    it('rejects unsupported key sequences instead of making them recursive', () => {
        const cm = createAdapter()

        expect(() => createNonrecursiveVimMapping('j', 'kk', 'normal')).toThrow("isn't supported by noremap")

        Vim.handleKey(cm, 'j')
        expect(cm.getCursor().line).toBe(2)
    })
})
