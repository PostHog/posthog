import { Monaco } from '@monaco-editor/react'
import { languages } from 'monaco-editor'

export const conf: () => languages.LanguageConfiguration = () => ({
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
    }
}
