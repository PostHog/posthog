/* oxlint-disable no-useless-escape */
// Adapted from: https://raw.githubusercontent.com/microsoft/monaco-editor/main/src/basic-languages/typescript/typescript.ts
import { Monaco } from '@monaco-editor/react'
import { languages } from 'monaco-editor'

import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'

import { HogLanguage } from '~/queries/schema/schema-general'

export const conf: () => languages.LanguageConfiguration = () => ({
    wordPattern: /(-?\d*\.\d\w*)|([^\`\~\!\@\#\%\^\&\*\(\)\-\=\+\[\{\]\}\\\|\;\:\'\"\,\.\<\>\/\?\s]+)/g,

    comments: {
        lineComment: '//',
        blockComment: ['/*', '*/'],
    },

    brackets: [
        ['{', '}'],
        ['[', ']'],
        ['(', ')'],
    ],

    onEnterRules: [
        {
            // e.g. /** | */
            beforeText: /^\s*\/\*\*(?!\/)([^\*]|\*(?!\/))*$/,
            afterText: /^\s*\*\/$/,
            action: {
                indentAction: languages.IndentAction.IndentOutdent,
                appendText: ' * ',
            },
        },
        {
            // e.g. /** ...|
            beforeText: /^\s*\/\*\*(?!\/)([^\*]|\*(?!\/))*$/,
            action: {
                indentAction: languages.IndentAction.None,
                appendText: ' * ',
            },
        },
        {
            // e.g.  * ...|
            beforeText: /^(\t|(\ \ ))*\ \*(\ ([^\*]|\*(?!\/))*)?$/,
            action: {
                indentAction: languages.IndentAction.None,
                appendText: '* ',
            },
        },
        {
            // e.g.  */|
            beforeText: /^(\t|(\ \ ))*\ \*\/\s*$/,
            action: {
                indentAction: languages.IndentAction.None,
                removeText: 1,
            },
        },
    ],

    autoClosingPairs: [
        { open: '{', close: '}' },
        { open: '[', close: ']' },
        { open: '(', close: ')' },
        { open: '"', close: '"', notIn: ['string'] },
        { open: "'", close: "'", notIn: ['string', 'comment'] },
        { open: '`', close: '`', notIn: ['string', 'comment'] },
        { open: '/**', close: ' */', notIn: ['string'] },
    ],

    folding: {
        markers: {
            start: new RegExp('^\\s*//\\s*#?region\\b'),
            end: new RegExp('^\\s*//\\s*#?endregion\\b'),
        },
    },
})

export const language: () => languages.IMonarchLanguage = () => ({
    // Set defaultToken to invalid to see what you do not tokenize yet
    defaultToken: 'invalid',
    tokenPostfix: '.hog',

    keywords: [
        'fn',
        'let',
        'if',
        'else',
        'return',
        'true',
        'false',
        'null',
        'for',
        'while',
        'like',
        'ilike',
        'not',
        'and',
        'or',
        'in',
    ],
    operators: [
        '<=',
        '>=',
        '==',
        '!=',
        '=>',
        '+',
        '-',
        '**',
        '*',
        '/',
        '%',
        '<<',
        '</',
        '>>',
        '>>>',
        '&',
        '|',
        '^',
        '!',
        '~',
        '||',
        '??',
        '?',
        ':',
        '=',
        ':=',
        '+=',
        '-=',
        '*=',
        '*=~',
        '!=',
        '!=~',
    ],

    // we include these common regular expressions
    symbols: /[=><!~?:&|+\-*\/\^%]+/,
    escapes: /\\(?:[abfnrtv\\"']|x[0-9A-Fa-f]{1,4}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})/,
    digits: /\d+(_+\d+)*/,

    // The main tokenizer for our languages
    tokenizer: {
        root: [[/[{}]/, 'delimiter.bracket'], { include: 'common' }],

        common: [
            // whitespace
            { include: '@whitespace' },

            // delimiters and operators
            [/[()\[\]]/, '@brackets'],
            [/[<>](?!@symbols)/, '@brackets'],
            [/!(?=([^=]|$))/, 'delimiter'],
            [
                /@symbols/,
                {
                    cases: {
                        '@operators': 'delimiter',
                        '@default': '',
                    },
                },
            ],

            // numbers
            [/(@digits)[eE]([\-+]?(@digits))?/, 'number.float'],
            [/(@digits)\.(@digits)([eE][\-+]?(@digits))?/, 'number.float'],
            [/(@digits)n?/, 'number'],

            // delimiter: after number because of .\d floats
            [/[;,.]/, 'delimiter'],

            // strings that are actually fields, show as type.identifier to highlight
            [/"([^"\\]|\\.)*$/, 'type.identifier.invalid'], // non-teminated type.identifier
            [/'([^'\\]|\\.)*$/, 'type.identifier.invalid'], // non-teminated type.identifier
            [/"/, 'type.identifier', '@string_double'],
            [/`/, 'type.identifier', '@string_backtick'],

            // strings
            [/f'/, 'string', '@string_format'],
            [/'/, 'string', '@string_single'],

            // identifiers and keywords
            [
                /#?[a-z_$][\w$]*/,
                {
                    cases: {
                        '@keywords': 'keyword',
                        '@default': 'identifier',
                    },
                },
            ],
        ],

        whitespace: [
            [/[ \t\r\n]+/, ''],
            [/\/\*\*(?!\/)/, 'comment.doc', '@jsdoc'],
            [/\/\*/, 'comment', '@comment'],
            [/\/\/.*$/, 'comment'],
            [/--.*$/, 'comment'],
        ],

        comment: [
            [/[^\/*]+/, 'comment'],
            [/\*\//, 'comment', '@pop'],
            [/[\/*]/, 'comment'],
        ],

        jsdoc: [
            [/[^\/*]+/, 'comment.doc'],
            [/\*\//, 'comment.doc', '@pop'],
            [/[\/*]/, 'comment.doc'],
        ],

        string_double: [
            [/[^\\"]+/, 'type.identifier'],
            [/@escapes/, 'type.identifier.escape'],
            [/\\./, 'type.identifier.escape.invalid'],
            [/"/, 'type.identifier', '@pop'],
        ],

        string_backtick: [
            [/[^\\`]+/, 'type.identifier'],
            [/@escapes/, 'type.identifier.escape'],
            [/\\./, 'type.identifier.escape.invalid'],
            [/`/, 'type.identifier', '@pop'],
        ],

        string_single: [
            [/[^\\']+/, 'string'],
            [/@escapes/, 'string.escape'],
            [/\\./, 'string.escape.invalid'],
            [/'/, 'string', '@pop'],
        ],

        string_format: [
            [/\{/, { token: 'delimiter.bracket', next: '@bracketCounting' }],
            [/[^\\'{]+/, 'string'],
            [/@escapes/, 'string.escape'],
            [/\\./, 'string.escape.invalid'],
            [/'/, 'string', '@pop'],
        ],

        bracketCounting: [
            [/\{/, 'delimiter.bracket', '@bracketCounting'],
            [/\}/, 'delimiter.bracket', '@pop'],
            { include: 'common' },
        ],
    },
})

export function initHogLanguage(monaco: Monaco): void {
    if (!monaco.languages.getLanguages().some(({ id }) => id === 'hog')) {
        monaco.languages.register({ id: 'hog', extensions: ['.hog'], mimetypes: ['application/hog'] })
        monaco.languages.setLanguageConfiguration('hog', conf())
        monaco.languages.setMonarchTokensProvider('hog', language())
        monaco.languages.registerCompletionItemProvider('hog', hogQLAutocompleteProvider(HogLanguage.hog))
        monaco.languages.registerCodeActionProvider('hog', hogQLMetadataProvider())
    }
}

/* oxlint-enable no-useless-escape */
