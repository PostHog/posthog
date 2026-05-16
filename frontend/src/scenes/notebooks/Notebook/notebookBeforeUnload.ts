import type { NotebookSyncStatus } from '../types'
import type { NotebookLogicMode } from './notebookLogic'

export type ShouldWarnBeforeLeavingNotebookInput = {
    mode: NotebookLogicMode
    isLocalOnly: boolean
    isShared: boolean
    isEditable: boolean
    syncStatus: NotebookSyncStatus
    currentPathname: string
    newPathname?: string
}

/**
 * Pure decision helper for the unsaved-changes prompt. Returns `true` if the user should be
 * warned before navigating away. Extracted from the `beforeUnload` builder so it can be unit
 * tested without mounting the full `notebookLogic` (which connects a dozen other logics).
 */
export function shouldWarnBeforeLeavingNotebook(input: ShouldWarnBeforeLeavingNotebookInput): boolean {
    // Only guard real, server-backed notebooks that the current user can edit.
    // Scratchpad/canvas/templates are local-only, shared views are read-only.
    if (input.mode !== 'notebook' || input.isLocalOnly || input.isShared || !input.isEditable) {
        return false
    }
    // syncStatus is `unsaved` while there is local content not yet on the server, and `saving`
    // while a save is in flight (including the 409 retry loop in collab mode). Either way,
    // leaving now risks dropping changes.
    if (input.syncStatus !== 'unsaved' && input.syncStatus !== 'saving') {
        return false
    }
    // Ignore in-page URL updates (side panel, hash params, comment selection, ...).
    if (input.newPathname !== undefined && input.newPathname === input.currentPathname) {
        return false
    }
    return true
}
