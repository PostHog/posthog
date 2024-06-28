// eslint-disable-next-line eslint-comments/disable-enable-pair
/* eslint-disable no-useless-escape */
import { languages } from 'monaco-editor'

import { conf as _conf, language as _language } from './hog'

export const conf: () => languages.LanguageConfiguration = () => ({
    ..._conf(),
})

export const language: () => languages.IMonarchLanguage = () => ({
    ..._language(),
    tokenizer: {
        root: [{ include: 'template_string' }],

        template_string: [
            [/\{/, { token: 'delimiter.bracket', next: '@bracketCounting' }],
            [/[^{]+/, 'text'], // using "text" not "string" to keep the text field black
            [/@escapes/, 'text.escape'],
            [/\\./, 'text.escape.invalid'],
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

        bracketCounting: [
            [/\{/, 'delimiter.bracket', '@bracketCounting'],
            [/\}/, 'delimiter.bracket', '@pop'],
            { include: 'hog' },
        ],
    },
})
