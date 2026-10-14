import { languages } from 'monaco-editor'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

export const hogQLFormattingProvider: () => languages.DocumentFormattingEditProvider = () => ({
    provideDocumentFormattingEdits: async (model, options) => {
        const { formatHogQL } = await import('./formatHogQL')
        const query = model.getValue()
        const formatted = formatHogQL(query, { tabWidth: options.tabSize, useTabs: !options.insertSpaces })
        posthog.capture('sql-editor-query-formatted', {
            succeeded: formatted !== null,
            changed: formatted !== null && formatted !== query,
        })
        if (formatted === null) {
            lemonToast.error("Couldn't format this query. Check it for syntax errors and try again.")
            return []
        }
        if (formatted === query) {
            return []
        }
        return [{ range: model.getFullModelRange(), text: formatted }]
    },
})
