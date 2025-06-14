import { BuiltLogic } from 'kea'
import type { codeEditorLogicType } from 'lib/monaco/codeEditorLogicType'
import { languages } from 'monaco-editor'

import { performQuery } from '~/queries/query'
import {
    AutocompleteCompletionItemKind,
    HogLanguage,
    HogQLAutocomplete,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

const convertCompletionItemKind = (kind: AutocompleteCompletionItemKind): languages.CompletionItemKind => {
    switch (kind) {
        case 'Method':
            return languages.CompletionItemKind.Method
        case 'Function':
            return languages.CompletionItemKind.Function
        case 'Constructor':
            return languages.CompletionItemKind.Constructor
        case 'Field':
            return languages.CompletionItemKind.Field
        case 'Variable':
            return languages.CompletionItemKind.Variable
        case 'Class':
            return languages.CompletionItemKind.Class
        case 'Struct':
            return languages.CompletionItemKind.Struct
        case 'Interface':
            return languages.CompletionItemKind.Interface
        case 'Module':
            return languages.CompletionItemKind.Module
        case 'Property':
            return languages.CompletionItemKind.Property
        case 'Event':
            return languages.CompletionItemKind.Event
        case 'Operator':
            return languages.CompletionItemKind.Operator
        case 'Unit':
            return languages.CompletionItemKind.Unit
        case 'Value':
            return languages.CompletionItemKind.Value
        case 'Constant':
            return languages.CompletionItemKind.Constant
        case 'Enum':
            return languages.CompletionItemKind.Enum
        case 'EnumMember':
            return languages.CompletionItemKind.EnumMember
        case 'Keyword':
            return languages.CompletionItemKind.Keyword
        case 'Text':
            return languages.CompletionItemKind.Text
        case 'Color':
            return languages.CompletionItemKind.Color
        case 'File':
            return languages.CompletionItemKind.File
        case 'Reference':
            return languages.CompletionItemKind.Reference
        case 'Customcolor':
            return languages.CompletionItemKind.Customcolor
        case 'Folder':
            return languages.CompletionItemKind.Folder
        case 'TypeParameter':
            return languages.CompletionItemKind.TypeParameter
        case 'User':
            return languages.CompletionItemKind.User
        case 'Issue':
            return languages.CompletionItemKind.Issue
        case 'Snippet':
            return languages.CompletionItemKind.Snippet
        default:
            throw new Error(`Unknown CompletionItemKind: ${kind}`)
    }
}

const kindToSortText = (kind: AutocompleteCompletionItemKind, label: string): string => {
    if (kind === 'Variable') {
        return `1-${label}`
    }
    if (kind === 'Method' || kind === 'Function') {
        return `2-${label}`
    }
    return `3-${label}`
}

export const hogQLAutocompleteProvider = (type: HogLanguage): languages.CompletionItemProvider => ({
    triggerCharacters: [' ', ',', '.', '{'],
    provideCompletionItems: async (model, position) => {
        const logic: BuiltLogic<codeEditorLogicType> | undefined = (model as any).codeEditorLogic
        if (!logic || !logic.isMounted()) {
            return {
                suggestions: [],
                incomplete: false,
            }
        }
        const word = model.getWordUntilPosition(position)
        const startOffset = model.getOffsetAt({
            lineNumber: position.lineNumber,
            column: word.startColumn,
        })
        const endOffset = model.getOffsetAt({
            lineNumber: position.lineNumber,
            column: word.endColumn,
        })
        const query: HogQLAutocomplete = setLatestVersionsOnQuery(
            {
                kind: NodeKind.HogQLAutocomplete,
                language: type,
                // Use the text from the model instead of logic due to a race condition on the logic values updating quick enough
                query: model.getValue(),
                filters: logic.isMounted() ? logic.props.metadataFilters : undefined,
                globals: logic.isMounted() ? logic.props.globals : undefined,
                sourceQuery: logic.isMounted() ? logic.props.sourceQuery : undefined,
                startPosition: startOffset,
                endPosition: endOffset,
            },
            { recursion: false }
        )
        const response = await performQuery<HogQLAutocomplete>(query)
        const completionItems = response.suggestions
        const suggestions = completionItems.map<languages.CompletionItem>((item) => {
            const kind = convertCompletionItemKind(item.kind)
            const sortText = kindToSortText(item.kind, item.label)

            return {
                label: {
                    label: item.label,
                    detail: item.detail,
                },
                documentation: item.documentation,
                insertText: item.insertText,
                range: {
                    startLineNumber: position.lineNumber,
                    endLineNumber: position.lineNumber,
                    startColumn: word.startColumn,
                    endColumn: word.endColumn,
                },
                kind,
                sortText,
                command:
                    kind === languages.CompletionItemKind.Function
                        ? {
                              id: 'cursorLeft',
                              title: 'Move cursor left',
                          }
                        : undefined,
            }
        })

        return {
            suggestions,
            incomplete: response.incomplete_list,
        }
    },
})
