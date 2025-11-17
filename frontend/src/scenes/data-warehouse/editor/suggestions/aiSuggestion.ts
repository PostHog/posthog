import { multitabEditorLogicType } from '../multitabEditorLogicType'

// Handlers for AI query suggestions

export const aiSuggestionOnAcceptText = 'Accept'
export const aiSuggestionOnRejectText = 'Reject'

export const aiSuggestionOnAccept = (
    shouldRunQuery: boolean,
    actions: multitabEditorLogicType['actions'],
    values: multitabEditorLogicType['values'],
    props: multitabEditorLogicType['props']
): void => {
    actions.reportAIQueryAccepted()

    // Get the current editor content (which includes any user edits to the suggestion)
    let currentEditorContent = values.suggestedQueryInput

    if (props.editor) {
        // If we're in diff mode, get the current content from the modified editor
        if ('getModifiedEditor' in props.editor) {
            const modifiedEditor = (props.editor as any).getModifiedEditor()
            currentEditorContent = modifiedEditor.getValue()
        } else {
            // Regular editor
            currentEditorContent = props.editor.getValue()
        }
    }

    actions.setQueryInput(currentEditorContent)

    if (shouldRunQuery) {
        actions.runQuery(currentEditorContent)
    }
}

export const aiSuggestionOnReject = (
    actions: multitabEditorLogicType['actions'],
    values: multitabEditorLogicType['values']
): void => {
    actions.reportAIQueryRejected()
    // Revert to the original query content (before AI's suggestion and before any user edits)
    // This is stored in suggestionPayload.originalValue when the suggestion was created
    const originalContent = values.suggestionPayload?.originalValue || values.queryInput
    actions.setQueryInput(originalContent)
}
