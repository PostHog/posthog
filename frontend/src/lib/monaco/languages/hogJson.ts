/* oxlint-disable no-useless-escape */
import { Monaco } from '@monaco-editor/react'
import { languages } from 'monaco-editor'

import { hogQLAutocompleteProvider } from 'lib/monaco/hogQLAutocompleteProvider'
import { hogQLMetadataProvider } from 'lib/monaco/hogQLMetadataProvider'

import { HogLanguage } from '~/queries/schema/schema-general'

import { conf as _conf, language as _language } from './hog'

export const conf: () => languages.LanguageConfiguration = () => ({
    ..._conf(),
})

export const language: () => languages.IMonarchLanguage = () => ({
    ..._language(),
    jsonKeywords: ['true', 'false', 'null', 'undefined'],
    tokenizer: {
        root: [[/[{}]/, 'delimiter.bracket'], { include: 'json' }],

        json: [
            // whitespace
            { include: '@whitespace' },

            // numbers
            [/(@digits)[eE]([\-+]?(@digits))?/, 'number.float'],
            [/(@digits)\.(@digits)([eE][\-+]?(@digits))?/, 'number.float'],
            [/(@digits)n?/, 'number'],
            [
                /[\w@]+/,
                {
                    cases: {
                        '@jsonKeywords': 'keyword',
                    },
                },
            ],

            // delimiter: after number because of .\d floats
            [/[;,.]/, 'delimiter'],

            // strings
            [/"([^"\\]|\\.)*$/, 'string.invalid'], // non-teminated string
            [/"/, 'string', '@string_format_json'],
        ],

        hog: [
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

        string_format_json: [
            [/\{/, { token: 'delimiter.bracket', next: '@bracketCounting' }],
            [/[^\\"{]+/, 'string'],
            [/@escapes/, 'string.escape'],
            [/\\./, 'string.escape.invalid'],
            [/"/, 'string', '@pop'],
        ],

        bracketCounting: [
            [/\{/, 'delimiter.bracket', '@bracketCounting'],
            [/\}/, 'delimiter.bracket', '@pop'],
            { include: 'hog' },
        ],
    },
})

export function initHogJsonLanguage(monaco: Monaco): void {
    if (!monaco.languages.getLanguages().some(({ id }) => id === 'hogJson')) {
        monaco.languages.register({
            id: 'hogJson',
            mimetypes: ['application/hog+json'],
        })
        monaco.languages.setLanguageConfiguration('hogJson', conf())
        monaco.languages.setMonarchTokensProvider('hogJson', language())
        monaco.languages.registerCompletionItemProvider('hogJson', hogQLAutocompleteProvider(HogLanguage.hogJson))
        monaco.languages.registerCodeActionProvider('hogJson', hogQLMetadataProvider())
    }
}
/* oxlint-enable no-useless-escape */
