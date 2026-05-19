import { languages } from 'monaco-editor'

import { formatQueries } from 'scenes/data-warehouse/editor/multiQueryUtils'

/** Monaco document formatter for the `hogQL` language. Wired up automatically
 *  to Shift+Alt+F, the right-click "Format document" menu item, and the
 *  `editor.action.formatDocument` command. Handles multi-statement documents
 *  (`;`-separated). Returns no edits when the input isn't well-formed, leaving
 *  the user's text untouched. */
export function hogQLFormattingProvider(): languages.DocumentFormattingEditProvider {
    return {
        async provideDocumentFormattingEdits(model) {
            const original = model.getValue()
            if (!original.trim()) {
                return []
            }
            const result = await formatQueries(original)
            if (!result.ok || result.output === original) {
                return []
            }
            return [{ range: model.getFullModelRange(), text: result.output }]
        },
    }
}
