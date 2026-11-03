import type { Monaco } from '@monaco-editor/react'
import type { BuiltLogic } from 'kea'
import { editor, languages } from 'monaco-editor'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { retryImport } from 'lib/utils/retryImport'

import { HogLanguage } from '~/queries/schema/schema-general'

import type { codeEditorLogicType } from './codeEditorLogic'
import type { FormatHogQLFailure, FormatHogQLResult } from './formatHogQL'

const FAILURE_MESSAGES: Record<FormatHogQLFailure | 'raw_sql', string> = {
    raw_sql: 'Formatting is only available for HogQL queries. Turn off "Send raw query" to format this one.',
    too_large: 'This query is too long or too deeply nested to format. Split it into smaller queries.',
    unparsable: "Couldn't format this query. Check it for syntax errors and try again.",
    unsupported: "Couldn't format this query. It uses syntax the formatter does not support yet.",
    unverified: "Couldn't format this query. Try again in a moment.",
}

function isRawSqlModel(model: editor.ITextModel): boolean {
    const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
    const sourceQuery = logic?.props.sourceQuery
    return !!sourceQuery && 'sendRawQuery' in sourceQuery && !!sourceQuery.sendRawQuery
}

async function formatQuery(query: string, options: languages.FormattingOptions): Promise<FormatHogQLResult> {
    try {
        const { formatHogQL } = await retryImport(() => import('./formatHogQL'))
        return await formatHogQL(query, { tabWidth: options.tabSize, useTabs: !options.insertSpaces })
    } catch (error) {
        posthog.captureException(error)
        return { formatted: null, failure: 'unverified' }
    }
}

export const hogQLFormattingProvider: () => languages.DocumentFormattingEditProvider = () => ({
    provideDocumentFormattingEdits: async (model, options) => {
        const query = model.getValue(editor.EndOfLinePreference.LF)
        const result = isRawSqlModel(model)
            ? ({ formatted: null, failure: 'raw_sql' } as const)
            : await formatQuery(query, options)
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

const monacosWithFormatting = new WeakSet<Monaco>()

export function registerHogQLFormattingProvider(monaco: Monaco): void {
    if (monacosWithFormatting.has(monaco)) {
        return
    }
    monacosWithFormatting.add(monaco)
    monaco.languages.registerDocumentFormattingEditProvider(HogLanguage.hogQL, hogQLFormattingProvider())
}
