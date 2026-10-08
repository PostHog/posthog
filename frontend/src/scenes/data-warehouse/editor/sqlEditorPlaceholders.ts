/** A `{name}` placeholder that the scene embedding the editor fills in when it runs the query for real. */
export interface SQLEditorPlaceholder {
    name: string
    description: string
    /** Stands in for the real value whenever the editor runs or checks the query. */
    previewValue: string
}

export function placeholderPreviewValues(placeholders: SQLEditorPlaceholder[]): Record<string, string> | null {
    if (placeholders.length === 0) {
        return null
    }
    return Object.fromEntries(placeholders.map((placeholder) => [placeholder.name, placeholder.previewValue]))
}
