import type { sqlEditorLogicType } from '../sqlEditorLogic'

// Handlers for restoring a previous version of a saved query from the history modal.
// Restoring only updates the editor content — the user persists it through the normal
// "Update view" flow, which keeps conflict detection and writes a new activity log entry.

export const queryHistorySuggestionOnAcceptText = 'Restore'
export const queryHistorySuggestionOnRejectText = 'Cancel'

export const queryHistorySuggestionOnAccept = (
    shouldRunQuery: boolean,
    actions: sqlEditorLogicType['actions'],
    values: sqlEditorLogicType['values'],
    props: sqlEditorLogicType['props']
): void => {
    // Get the current editor content (which includes any user edits to the restored version)
    let currentEditorContent = values.suggestedQueryInput

    if (props.editor) {
        // If we're in diff mode, get the current content from the modified editor
        if ('getModifiedEditor' in props.editor) {
            const modifiedEditor = (props.editor as any).getModifiedEditor()
            currentEditorContent = modifiedEditor.getValue()
        } else {
            currentEditorContent = props.editor.getValue()
        }
    }

    actions.setQueryInput(currentEditorContent)

    if (shouldRunQuery) {
        actions.runQuery(currentEditorContent)
    }
}

export const queryHistorySuggestionOnReject = (
    actions: sqlEditorLogicType['actions'],
    values: sqlEditorLogicType['values']
): void => {
    // Revert to the content from before the restore was initiated
    const originalContent = values.suggestionPayload?.originalValue || values.queryInput
    actions.setQueryInput(originalContent)
}
