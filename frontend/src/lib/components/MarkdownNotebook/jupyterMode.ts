import { DragEvent, createContext, useContext, useSyncExternalStore } from 'react'

import type { NotebookComponentRunHandler } from './componentRunHandlers'
import type { NotebookJupyterCompletions } from './jupyterEditorKeys'
import type { NotebookComponentBlockNode } from './types'

export type MarkdownNotebookJupyterModeConfig = {
    cellTagNames: string[]
    newCellTagName: string
    /** The source a cell turns into when the M key converts it to markdown. */
    getCellSource: (node: NotebookComponentBlockNode) => string
    /** The cell with new source, as a merge or split leaves it. Clears output the new source did not produce. */
    withCellSource: (node: NotebookComponentBlockNode, source: string) => NotebookComponentBlockNode
    /** Gives a pasted or restored copy of a cell identities of its own, such as a fresh run id. */
    prepareCellCopy?: (node: NotebookComponentBlockNode) => NotebookComponentBlockNode
    onRestartKernel?: () => void
    /** Called for every command a key, the toolbar, or a cell button runs, so the host can count usage. */
    onCommand?: (command: NotebookJupyterCommand) => void
    completeCode?: (
        node: NotebookComponentBlockNode,
        code: string,
        cursorPos: number
    ) => Promise<NotebookJupyterCompletions | null>
    inspectCode?: (node: NotebookComponentBlockNode, code: string, cursorPos: number) => Promise<string | null>
}

export type NotebookJupyterCommand =
    | 'run'
    | 'run-and-advance'
    | 'run-and-insert-below'
    | 'enter-edit-mode'
    | 'enter-command-mode'
    | 'insert-above'
    | 'insert-below'
    | 'delete'
    | 'undo-delete'
    | 'copy'
    | 'cut'
    | 'paste-below'
    | 'paste-above'
    | 'to-markdown'
    | 'to-code'
    | 'merge'
    | 'split'
    | 'select-previous'
    | 'select-next'
    | 'extend-selection-up'
    | 'extend-selection-down'
    | 'move-up'
    | 'move-down'
    | 'interrupt'
    | 'restart-kernel'
    | 'toggle-output'
    | 'toggle-line-numbers'
    | 'show-shortcuts'

export type NotebookJupyterKeyInput = {
    key: string
    shiftKey: boolean
    altKey: boolean
    metaKey: boolean
    ctrlKey: boolean
    /** True when the key reached the cell while its source was being edited (edit mode). */
    inEditor: boolean
}

export type NotebookJupyterPendingKey = { key: string; at: number }

export const JUPYTER_KEY_SEQUENCE_MS = 800

const SEQUENCE_COMMANDS: Record<string, NotebookJupyterCommand> = {
    d: 'delete',
    i: 'interrupt',
    '0': 'restart-kernel',
}

const COMMAND_MODE_KEYS: Record<string, NotebookJupyterCommand> = {
    Delete: 'delete',
    Backspace: 'delete',
    a: 'insert-above',
    b: 'insert-below',
    z: 'undo-delete',
    c: 'copy',
    x: 'cut',
    v: 'paste-below',
    m: 'to-markdown',
    y: 'to-code',
    k: 'select-previous',
    ArrowUp: 'select-previous',
    j: 'select-next',
    ArrowDown: 'select-next',
    o: 'toggle-output',
    l: 'toggle-line-numbers',
    h: 'show-shortcuts',
    Enter: 'enter-edit-mode',
}

const SHIFTED_COMMAND_MODE_KEYS: Record<string, NotebookJupyterCommand> = {
    v: 'paste-above',
    m: 'merge',
    l: 'toggle-line-numbers',
    k: 'extend-selection-up',
    ArrowUp: 'extend-selection-up',
    j: 'extend-selection-down',
    ArrowDown: 'extend-selection-down',
}

function isSplitKey({ key, shiftKey, ctrlKey, metaKey, altKey }: NotebookJupyterKeyInput): boolean {
    // Shift turns the minus key into an underscore on most layouts, so accept both.
    return (key === '-' || key === '_' || key === 'Minus') && shiftKey && (ctrlKey || metaKey) && !altKey
}

/**
 * Maps a key press on a cell to the Jupyter command it stands for. Two-key sequences (`D D`) carry
 * their first key in `pending`, which the caller keeps and passes back on the next press.
 */
export function resolveNotebookJupyterKey(
    input: NotebookJupyterKeyInput,
    pending: NotebookJupyterPendingKey | null,
    now: number
): { command: NotebookJupyterCommand | null; pending: NotebookJupyterPendingKey | null } {
    const { key, shiftKey, altKey, metaKey, ctrlKey, inEditor } = input
    const modKey = metaKey || ctrlKey

    if (key === 'Enter') {
        if (altKey && !modKey && !shiftKey) {
            return { command: 'run-and-insert-below', pending: null }
        }
        if (modKey && !altKey && !shiftKey) {
            return { command: 'run', pending: null }
        }
        if (shiftKey && !modKey && !altKey) {
            return { command: 'run-and-advance', pending: null }
        }
    }

    if (inEditor) {
        if (key === 'Escape' && !shiftKey && !altKey && !modKey) {
            return { command: 'enter-command-mode', pending: null }
        }
        if (isSplitKey(input)) {
            return { command: 'split', pending: null }
        }
        return { command: null, pending: null }
    }

    if (modKey && shiftKey && !altKey && (key === 'ArrowUp' || key === 'ArrowDown')) {
        return { command: key === 'ArrowUp' ? 'move-up' : 'move-down', pending: null }
    }

    // The editor's own shortcuts (save, select all, copy) keep every other modifier combination.
    if (modKey || altKey) {
        return { command: null, pending: null }
    }

    const normalizedKey = key.length === 1 ? key.toLowerCase() : key

    if (shiftKey) {
        return { command: SHIFTED_COMMAND_MODE_KEYS[normalizedKey] ?? null, pending: null }
    }

    const sequenceCommand = SEQUENCE_COMMANDS[normalizedKey]
    if (sequenceCommand) {
        if (pending?.key === normalizedKey && now - pending.at <= JUPYTER_KEY_SEQUENCE_MS) {
            return { command: sequenceCommand, pending: null }
        }
        return { command: null, pending: { key: normalizedKey, at: now } }
    }

    return { command: COMMAND_MODE_KEYS[normalizedKey] ?? null, pending: null }
}

type NotebookJupyterDeletedCells = { markdown: string; index: number }[]

type NotebookJupyterStoreState = {
    /** The selected cell, named by its first node's id. Kept while the notebook toolbar has focus. */
    activeCellId: string | null
    /** Every selected cell, the active one included. More than one only after Shift+Up/Down. */
    selectedCellIds: ReadonlySet<string>
    editFocusRequestNodeId: string | null
    lineNumbers: boolean
    shortcutsOpen: boolean
    runHandlers: ReadonlyMap<string, NotebookComponentRunHandler>
}

const NO_CELLS: ReadonlySet<string> = new Set()

/**
 * Cell state shared between the cells and the notebook toolbar. It sits outside React state so a
 * change re-renders only the cells whose selected slice changed, and never the whole canvas.
 */
export class NotebookJupyterStore {
    private state: NotebookJupyterStoreState = {
        activeCellId: null,
        selectedCellIds: NO_CELLS,
        editFocusRequestNodeId: null,
        lineNumbers: false,
        shortcutsOpen: false,
        runHandlers: new Map(),
    }
    private listeners = new Set<() => void>()

    pendingKey: NotebookJupyterPendingKey | null = null
    /** The end of a Shift+Up/Down selection that stays put while the active cell moves. */
    selectionAnchorCellId: string | null = null
    clipboard: string | null = null
    deletedCells: NotebookJupyterDeletedCells[] = []

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
    }

    getState = (): NotebookJupyterStoreState => this.state

    private update(patch: Partial<NotebookJupyterStoreState>): void {
        this.state = { ...this.state, ...patch }
        this.listeners.forEach((listener) => listener())
    }

    setActiveCell(activeCellId: string | null, selectedCellIds?: string[]): void {
        const nextSelection = selectedCellIds ?? (activeCellId ? [activeCellId] : [])
        if (!selectedCellIds) {
            this.selectionAnchorCellId = activeCellId
        }
        const current = this.state.selectedCellIds
        const isSameSelection =
            current.size === nextSelection.length && nextSelection.every((cellId) => current.has(cellId))
        if (this.state.activeCellId === activeCellId && isSameSelection) {
            return
        }
        this.update({
            activeCellId,
            selectedCellIds: isSameSelection ? current : new Set(nextSelection),
        })
    }

    requestEditFocus(nodeId: string | null): void {
        this.update({ editFocusRequestNodeId: nodeId })
    }

    toggleLineNumbers(): void {
        this.update({ lineNumbers: !this.state.lineNumbers })
    }

    setShortcutsOpen(shortcutsOpen: boolean): void {
        this.update({ shortcutsOpen })
    }

    setRunHandler(nodeId: string, handler: NotebookComponentRunHandler | null): void {
        const current = this.state.runHandlers.get(nodeId) ?? null
        if (current === handler) {
            return
        }
        const runHandlers = new Map(this.state.runHandlers)
        if (handler) {
            runHandlers.set(nodeId, handler)
        } else {
            runHandlers.delete(nodeId)
        }
        this.update({ runHandlers })
    }
}

export type NotebookJupyterCommands = {
    config: MarkdownNotebookJupyterModeConfig
    store: NotebookJupyterStore
    /** Runs a command against a cell, or against the selection when the command acts on several. */
    executeCommand: (command: NotebookJupyterCommand, cellId: string | null) => void
    /** Adds a code cell next to a node; with no node it goes after the last cell. */
    insertCell: (nodeId: string | null, position: 'above' | 'below', options?: { edit?: boolean }) => void
    /** Splits a code cell's source at `offset`; the part after it becomes a new cell below. */
    splitCell: (nodeId: string, offset: number) => void
    moveEditFocus: (cellId: string, direction: 'previous' | 'next') => void
    /** Removes a cell whose editor was emptied with Backspace, and edits the end of the cell above. */
    deleteEmptyCell: (cellId: string) => void
    getCellKind: (cellId: string | null) => 'code' | 'markdown' | 'block' | null
    /** Starts moving a cell by drag, from anywhere its prompt column covers. */
    startCellDrag: (event: DragEvent<HTMLDivElement>, nodeId: string) => void
    endCellDrag: () => void
}

export const NotebookJupyterContext = createContext<NotebookJupyterCommands | null>(null)

export function useNotebookJupyterCommands(): NotebookJupyterCommands | null {
    return useContext(NotebookJupyterContext)
}

const EMPTY_STORE_STATE: NotebookJupyterStoreState = new NotebookJupyterStore().getState()
const noopSubscribe = (): (() => void) => () => {}

export function useNotebookJupyterStoreValue<T>(selector: (state: NotebookJupyterStoreState) => T): T {
    const store = useContext(NotebookJupyterContext)?.store
    return useSyncExternalStore(store?.subscribe ?? noopSubscribe, () =>
        selector(store?.getState() ?? EMPTY_STORE_STATE)
    )
}
