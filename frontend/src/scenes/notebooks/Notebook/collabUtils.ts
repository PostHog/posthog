export function shouldUseNotebookCollab(
    collabEnabled: boolean,
    hasNotebook: boolean,
    hasPreviewContent: boolean
): boolean {
    return collabEnabled && hasNotebook && !hasPreviewContent
}

export function notebookEditorLogicKey(shortId: string, useCollab: boolean): string {
    return `Notebook.${shortId}${useCollab ? '-collab' : ''}`
}
