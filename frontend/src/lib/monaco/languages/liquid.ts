import { Monaco } from '@monaco-editor/react'
import { languages } from 'monaco-editor'

import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'

export const conf: () => languages.LanguageConfiguration = () => ({
    wordPattern: /(-?\d*\.\d\w*)|([^`~!@#$%^&*()\-=+[\]{}|;:'",.<>/?\s]+)/g,
    comments: {
        blockComment: ['{% comment %}', '{% endcomment %}'],
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
        { open: "'", close: "'" },
    ],
    surroundingPairs: [
        { open: '{', close: '}' },
        { open: '[', close: ']' },
        { open: '(', close: ')' },
        { open: '"', close: '"' },
        { open: "'", close: "'" },
    ],
})

export const language: () => languages.IMonarchLanguage = () => ({
    defaultToken: '',
    tokenPostfix: '.liquid',

    keywords: [
        'if',
        'else',
        'elsif',
        'unless',
        'end',
        'for',
        'in',
        'break',
        'continue',
        'assign',
        'capture',
        'case',
        'when',
        'comment',
        'raw',
        'tablerow',
        'endtablerow',
        'true',
        'false',
        'nil',
        'null',
        'empty',
        'blank',
        'present',
    ],

    operators: ['==', '!=', '>', '<', '>=', '<=', 'contains', 'and', 'or'],

    symbols: /[=><!~?:&|+\-*/^]+/,

    tokenizer: {
        root: [
            // Liquid tags
            [/\{%/, { token: 'delimiter.liquid', next: '@liquidTag' }],
            // Liquid variables
            [/\{\{/, { token: 'delimiter.liquid', next: '@liquidVariable' }],
            // Regular text
            [/[^{]+/, 'text'],
        ],

        liquidTag: [[/%\}/, { token: 'delimiter.liquid', next: '@pop' }], { include: '@liquidContent' }],

        liquidVariable: [[/\}\}/, { token: 'delimiter.liquid', next: '@pop' }], { include: '@liquidContent' }],

        liquidContent: [
            // Keywords
            [
                /[a-zA-Z_]\w*/,
                {
                    cases: {
                        '@keywords': 'keyword',
                        '@default': 'identifier',
                    },
                },
            ],

            // Operators
            [
                /@symbols/,
                {
                    cases: {
                        '@operators': 'operator',
                        '@default': '',
                    },
                },
            ],

            // Numbers
            [/\d*\.\d+([eE][-+]?\d+)?/, 'number.float'],
            [/0[xX][0-9a-fA-F]+/, 'number.hex'],
            [/\d+/, 'number'],

            // Strings
            [/"([^"\\]|\\.)*$/, 'string.invalid'],
            [/'([^'\\]|\\.)*$/, 'string.invalid'],
            [/"/, 'string', '@string_double'],
            [/'/, 'string', '@string_single'],

            // Whitespace
            [/[ \t\r\n]+/, ''],
        ],

        string_double: [
            [/[^\\"]+/, 'string'],
            [/@escapes/, 'string.escape'],
            [/\\./, 'string.escape.invalid'],
            [/"/, 'string', '@pop'],
        ],

        string_single: [
            [/[^\\']+/, 'string'],
            [/@escapes/, 'string.escape'],
            [/\\./, 'string.escape.invalid'],
            [/'/, 'string', '@pop'],
        ],
    },
})

// Custom autocomplete provider for Liquid that provides basic completions from globals
const liquidAutocompleteProvider = (): languages.CompletionItemProvider => ({
    triggerCharacters: ['.', '{'],
    provideCompletionItems: async (model, position) => {
        const logic = (model as any).codeEditorLogic
        if (!logic || !logic.isMounted() || !logic.props.globals) {
            return { suggestions: [], incomplete: false }
        }

        const word = model.getWordUntilPosition(position)
        const range = {
            startLineNumber: position.lineNumber,
            endLineNumber: position.lineNumber,
            startColumn: word.startColumn,
            endColumn: word.endColumn,
        }

        const textBeforeCursor = model.getValueInRange({
            startLineNumber: position.lineNumber,
            startColumn: 1,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
        })

        const suggestions: languages.CompletionItem[] = []

        // Check if we're inside {{ }} or {% %}
        const inVariable = /\{\{[^}]*$/.test(textBeforeCursor)
        const inTag = /\{%[^%]*$/.test(textBeforeCursor)

        if (inVariable || inTag) {
            // Add top-level globals
            const globals = logic.props.globals
            Object.keys(globals).forEach((key) => {
                suggestions.push({
                    label: key,
                    kind: languages.CompletionItemKind.Variable,
                    insertText: key,
                    range,
                    sortText: `1-${key}`,
                })
            })

            // If after a dot, provide nested property suggestions
            const dotMatch = textBeforeCursor.match(/(\w+)\.(\w*)$/)
            if (dotMatch) {
                const [, objectName] = dotMatch
                if (globals[objectName] && typeof globals[objectName] === 'object') {
                    Object.keys(globals[objectName]).forEach((key) => {
                        suggestions.push({
                            label: key,
                            kind: languages.CompletionItemKind.Property,
                            insertText: key,
                            range,
                            sortText: `1-${key}`,
                        })
                    })
                }
            }
        }

        return { suggestions, incomplete: false }
    },
})

export function initLiquidLanguage(monaco: Monaco): void {
    if (!monaco.languages.getLanguages().some(({ id }) => id === 'liquid')) {
        monaco.languages.register({
            id: 'liquid',
            mimetypes: ['text/liquid'],
        })
        monaco.languages.setLanguageConfiguration('liquid', conf())
        monaco.languages.setMonarchTokensProvider('liquid', language())
        monaco.languages.registerCompletionItemProvider('liquid', liquidAutocompleteProvider())
        monaco.languages.registerCodeActionProvider('liquid', hogQLMetadataProvider())
    }
}
