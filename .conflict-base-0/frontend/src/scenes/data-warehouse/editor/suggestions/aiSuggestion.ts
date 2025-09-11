import { multitabEditorLogicType } from '../multitabEditorLogicType'

// Handlers for AI query suggestions

export const aiSuggestionOnAcceptText = 'Accept'
export const aiSuggestionOnRejectText = 'Reject'

export const aiSuggestionOnAccept = (
    shouldRunQuery: boolean,
    actions: multitabEditorLogicType['actions'],
    values: multitabEditorLogicType['values']
): void => {
    actions.reportAIQueryAccepted()
    actions.setQueryInput(values.suggestedQueryInput)

    if (shouldRunQuery) {
        actions.runQuery(values.suggestedQueryInput)
    }
}

export const aiSuggestionOnReject = (actions: multitabEditorLogicType['actions']): void => {
    actions.reportAIQueryRejected()
}
