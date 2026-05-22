import type { NotebookSyncStatus } from '../types'

export type ShouldWarnBeforeLeavingNotebookInput = {
    isLocalOnly: boolean
    isEditable: boolean
    syncStatus: NotebookSyncStatus
    currentPathname: string
    newPathname?: string
}

/**
 * Helper for the unsaved-changes prompt. Returns `true` if the user should be warned before
 * navigating away.
 *
 * `isLocalOnly` covers scratchpad / canvas / templates (no server save ever happens).
 * `isEditable` covers viewer-level access, history-preview mode, and shared/exported read-only
 * views (`<Notebook editable={false}>` flips `shouldBeEditable` off, which kills `isEditable`).
 * `syncStatus` is `unsaved` while there is local content not yet on the server, and `saving`
 * while a save is in flight (including the 409 retry loop in collab mode).
 */
export function shouldWarnBeforeLeavingNotebook(input: ShouldWarnBeforeLeavingNotebookInput): boolean {
    if (input.isLocalOnly || !input.isEditable) {
        return false
    }
    if (input.syncStatus !== 'unsaved' && input.syncStatus !== 'saving') {
        return false
    }
    // Ignore in-page URL updates (side panel, hash params, comment selection, ...).
    if (input.newPathname === input.currentPathname) {
        return false
    }
    return true
}
