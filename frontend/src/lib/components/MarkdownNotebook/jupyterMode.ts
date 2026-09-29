import { createContext, useContext, useSyncExternalStore } from 'react'

import type { NotebookComponentRunHandler } from './componentRunHandlers'
import type { NotebookComponentBlockNode } from './types'

export type MarkdownNotebookJupyterModeConfig = {
    cellTagNames: string[]
    newCellTagName: string
    /** The source a cell turns into when the M key converts it to markdown. */
    getCellSource: (node: NotebookComponentBlockNode) => string
    /** Gives a pasted or restored copy of a cell identities of its own, such as a fresh run id. */
    prepareCellCopy?: (node: NotebookComponentBlockNode) => NotebookComponentBlockNode
    onRestartKernel?: () => void
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
    | 'select-previous'
    | 'select-next'
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
    /** True when the key reached the cell from inside its code editor (edit mode). */
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
    a: 'insert-above',
    b: 'insert-below',
    z: 'undo-delete',
    c: 'copy',
    x: 'cut',
    v: 'paste-below',
    m: 'to-markdown',
    k: 'select-previous',
    ArrowUp: 'select-previous',
    j: 'select-next',
    ArrowDown: 'select-next',
    o: 'toggle-output',
    l: 'toggle-line-numbers',
    h: 'show-shortcuts',
    Enter: 'enter-edit-mode',
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

    if (normalizedKey === 'v' && shiftKey) {
        return { command: 'paste-above', pending: null }
    }

    const sequenceCommand = SEQUENCE_COMMANDS[normalizedKey]
    if (sequenceCommand && !shiftKey) {
        if (pending?.key === normalizedKey && now - pending.at <= JUPYTER_KEY_SEQUENCE_MS) {
            return { command: sequenceCommand, pending: null }
        }
        return { command: null, pending: { key: normalizedKey, at: now } }
    }

    if (shiftKey && normalizedKey !== 'l') {
        return { command: null, pending: null }
    }

    return { command: COMMAND_MODE_KEYS[normalizedKey] ?? null, pending: null }
}

type NotebookJupyterDeletedCell = { markdown: string; index: number }

type NotebookJupyterStoreState = {
    activeNodeId: string | null
    editFocusRequestNodeId: string | null
    lineNumbers: boolean
    shortcutsOpen: boolean
    runHandlers: ReadonlyMap<string, NotebookComponentRunHandler>
}

/**
 * Cell state shared between the cells and the notebook toolbar. It sits outside React state so a
 * change re-renders only the cells whose selected slice changed, and never the whole canvas.
 */
export class NotebookJupyterStore {
    private state: NotebookJupyterStoreState = {
        activeNodeId: null,
        editFocusRequestNodeId: null,
        lineNumbers: false,
        shortcutsOpen: false,
        runHandlers: new Map(),
    }
    private listeners = new Set<() => void>()

    pendingKey: NotebookJupyterPendingKey | null = null
    clipboard: string | null = null
    deletedCells: NotebookJupyterDeletedCell[] = []

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
    }

    getState = (): NotebookJupyterStoreState => this.state

    private update(patch: Partial<NotebookJupyterStoreState>): void {
        this.state = { ...this.state, ...patch }
        this.listeners.forEach((listener) => listener())
    }

    setActiveNodeId(activeNodeId: string | null): void {
        if (this.state.activeNodeId !== activeNodeId) {
            this.update({ activeNodeId })
        }
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
    insertCell: (nodeId: string | null, position: 'above' | 'below', options?: { edit?: boolean }) => void
    deleteCell: (nodeId: string) => void
    undoDeleteCell: () => boolean
    copyCell: (nodeId: string) => void
    cutCell: (nodeId: string) => void
    pasteCell: (nodeId: string | null, position: 'above' | 'below') => boolean
    moveCell: (nodeId: string, direction: 'up' | 'down') => boolean
    convertCellToMarkdown: (nodeId: string) => void
    selectAdjacentCell: (nodeId: string, direction: 'previous' | 'next') => boolean
    /** Selects the next block, or adds a cell in edit mode when the cell was the last one. */
    advanceFromCell: (nodeId: string) => void
    isCellNode: (nodeId: string) => boolean
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
