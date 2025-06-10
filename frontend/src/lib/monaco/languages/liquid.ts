import { Monaco } from '@monaco-editor/react'
import { languages } from 'monaco-editor'

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

export function initLiquidLanguage(monaco: Monaco): void {
    if (!monaco.languages.getLanguages().some(({ id }) => id === 'liquid')) {
        monaco.languages.register({
            id: 'liquid',
            mimetypes: ['text/liquid'],
        })
        monaco.languages.setLanguageConfiguration('liquid', conf())
        monaco.languages.setMonarchTokensProvider('liquid', language())
    }
}
