import type { BuiltLogic } from 'kea'
import { editor, languages } from 'monaco-editor'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { codeEditorLogicType } from './codeEditorLogic'
import type { FormatHogQLFailure } from './formatHogQL'

const FAILURE_MESSAGES: Record<FormatHogQLFailure | 'raw_sql', string> = {
    raw_sql: 'Formatting is only available for HogQL queries. Turn off "Send raw query" to format this one.',
    too_large: 'This query is too long or too deeply nested to format. Split it into smaller queries.',
    unparsable: "Couldn't format this query. Check it for syntax errors and try again.",
    unsupported: "Couldn't format this query. It uses syntax the formatter does not support yet.",
}

// A raw query goes to the external connection as written, in that connection's SQL dialect. The
// HogQL dialect would change the meaning of its literals, for example PostgreSQL's `$$...$$` strings.
function isRawSqlModel(model: editor.ITextModel): boolean {
    const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
    const sourceQuery = logic?.props.sourceQuery
    return !!sourceQuery && 'sendRawQuery' in sourceQuery && !!sourceQuery.sendRawQuery
}

export const hogQLFormattingProvider: () => languages.DocumentFormattingEditProvider = () => ({
    provideDocumentFormattingEdits: async (model, options) => {
        // The formatter emits LF line breaks, so compare against an LF view of a CRLF model too.
        const query = model.getValue(editor.EndOfLinePreference.LF)
        const { formatHogQL } = await import('./formatHogQL')
        const result = isRawSqlModel(model)
            ? ({ formatted: null, failure: 'raw_sql' } as const)
            : formatHogQL(query, { tabWidth: options.tabSize, useTabs: !options.insertSpaces })
        posthog.capture('sql-editor-query-formatted', {
            succeeded: result.failure === null,
            changed: result.formatted !== null && result.formatted !== query,
            failure: result.failure,
        })
        if (result.failure !== null) {
            lemonToast.error(FAILURE_MESSAGES[result.failure])
            return []
        }
        if (result.formatted === query) {
            return []
        }
        return [{ range: model.getFullModelRange(), text: result.formatted }]
    },
})
