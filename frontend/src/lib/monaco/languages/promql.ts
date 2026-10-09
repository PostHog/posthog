import { Monaco } from '@monaco-editor/react'
import { IPosition, editor, languages } from 'monaco-editor'

import { type PromQLCompletionItem, getPromQLCompletionProvider } from './promqlCompletionRegistry'

const itemKind = (monaco: Monaco, kind: PromQLCompletionItem['kind']): languages.CompletionItemKind => {
    const kinds = monaco.languages.CompletionItemKind
    switch (kind) {
        case 'function':
        case 'aggregation':
            return kinds.Function
        case 'metric':
            return kinds.Constructor
        case 'label':
            return kinds.Enum
        case 'value':
            return kinds.EnumMember
        case 'duration':
            return kinds.Unit
        case 'keyword':
            return kinds.Keyword
    }
}

const completionItemProvider = (monaco: Monaco): languages.CompletionItemProvider => ({
    triggerCharacters: ['{', ',', '(', '[', '=', '~', '"', ' ', ':'],
    provideCompletionItems: async (model: editor.ITextModel, position: IPosition) => {
        const provider = getPromQLCompletionProvider()
        if (!provider) {
            return { suggestions: [] }
        }
        const result = await provider(model.getValue(), model.getOffsetAt(position))
        if (!result) {
            return { suggestions: [] }
        }
        const start = model.getPositionAt(result.from)
        const range = {
            startLineNumber: start.lineNumber,
            startColumn: start.column,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
        }
        return {
            // The lists are searched on the server, so typing more must ask again.
            incomplete: true,
            suggestions: result.items.map((item) => ({
                label: item.label,
                kind: itemKind(monaco, item.kind),
                insertText: item.insertText,
                range,
                filterText: item.label,
                ...(item.detail ? { detail: item.detail } : {}),
                ...(item.documentation ? { documentation: item.documentation } : {}),
                ...(item.sortText ? { sortText: item.sortText } : {}),
                ...(item.snippet
                    ? { insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet }
                    : {}),
                ...(item.retrigger ? { command: { id: 'editor.action.triggerSuggest', title: 'Suggest' } } : {}),
            })),
        }
    },
})

export const conf: () => languages.LanguageConfiguration = () => ({
    // OTel metric and label names contain dots, so a word runs across them.
    wordPattern: /(-?\d*\.\d\w*)|([A-Za-z_$][\w:.]*)/,
    comments: {
        lineComment: '#',
    },
    brackets: [
        ['{', '}'],
        ['[', ']'],
        ['(', ')'],
    ],
    autoClosingPairs: [
        { open: '{', close: '}' },
        { open: '[', close: ']' },
        { open: '(', close: ')' },
        { open: '"', close: '"' },
    ],
})

export const language: () => languages.IMonarchLanguage = () => ({
    defaultToken: '',
    keywords: ['by', 'without', 'on', 'ignoring', 'group_left', 'group_right', 'bool', 'offset', 'and', 'or', 'unless'],
    aggregations: [
        'sum',
        'avg',
        'count',
        'min',
        'max',
        'stddev',
        'stdvar',
        'topk',
        'bottomk',
        'quantile',
        'count_values',
        'group',
        'limitk',
        'limit_ratio',
    ],
    tokenizer: {
        root: [
            [/#.*$/, 'comment'],
            [/"([^"\\]|\\.)*"/, 'string'],
            [/'([^'\\]|\\.)*'/, 'string'],
            [/`[^`]*`/, 'string'],
            [/\[[^\]]*\]/, 'number'],
            [/\d+(\.\d+)?(ms|s|m|h|d|w|y)/, 'number'],
            [/\d*\.?\d+([eE][+-]?\d+)?/, 'number'],
            [
                /[a-zA-Z_][\w:.]*(?=\s*\()/,
                { cases: { '@aggregations': 'keyword', '@keywords': 'keyword', '@default': 'type' } },
            ],
            [/[a-zA-Z_][\w:.]*/, { cases: { '@keywords': 'keyword', '@default': 'identifier' } }],
            [/=~|!~|!=|==|>=|<=|[-+*/%^<>=]/, 'operator'],
        ],
    },
})

export function initPromQLLanguage(monaco: Monaco): void {
    if (!monaco.languages.getLanguages().some((lang: { id: string }) => lang.id === 'promql')) {
        monaco.languages.register({ id: 'promql' })
        monaco.languages.setLanguageConfiguration('promql', conf())
        monaco.languages.setMonarchTokensProvider('promql', language())
        monaco.languages.registerCompletionItemProvider('promql', completionItemProvider(monaco))
    }
}
