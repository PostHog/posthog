import { SQLEditorMode } from '../sqlEditorModes'
import { BIEditorView, type BIQueryBuildResult } from './biEditorTypes'

export function canUseBIEditor(
    featureEnabled: boolean,
    mode: SQLEditorMode | undefined,
    sendRawQueryEnabled: boolean
): boolean {
    return featureEnabled && mode === SQLEditorMode.FullScene && !sendRawQueryEnabled
}

export function shouldConfirmEnteringBIEditor(
    nextEditorView: BIEditorView,
    queryInput: string | null | undefined,
    generatedQuery: BIQueryBuildResult | null
): boolean {
    const currentQuery = queryInput?.trim() ?? ''
    return (
        nextEditorView === BIEditorView.BI &&
        currentQuery.length > 0 &&
        currentQuery !== (generatedQuery?.query.trim() ?? '')
    )
}
