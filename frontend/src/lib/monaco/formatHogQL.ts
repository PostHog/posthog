import { type DialectOptions, clickhouse, expandPhrases, formatDialect } from 'sql-formatter'

import { retryImport } from 'lib/utils/retryImport'
import type { SelectComparison } from 'scenes/data-warehouse/editor/hogqlAst'

import { splitQueries } from './multiQueryUtils'

export interface FormatHogQLOptions {
    tabWidth?: number
    useTabs?: boolean
}

export type FormatHogQLFailure = 'too_large' | 'unparsable' | 'unsupported' | 'unverified'

export type FormatHogQLResult = { formatted: string; failure: null } | { formatted: null; failure: FormatHogQLFailure }

export const MAX_QUERY_LENGTH = 20_000
export const MAX_NESTING_DEPTH = 200

type Token = Parameters<NonNullable<DialectOptions['tokenizerOptions']['postProcess']>>[0][number]

const KEYWORD_TOKEN_TYPES = new Set<string>(['RESERVED_KEYWORD', 'RESERVED_DATA_TYPE'])

const KEYWORDS_FOLLOWED_BY_PARENS = new Set([
    'AND',
    'AS',
    'BETWEEN',
    'CASE',
    'COHORT',
    'DISTINCT',
    'ELSE',
    'END',
    'EXISTS',
    'ILIKE',
    'IN',
    'INTERVAL',
    'IS',
    'LIKE',
    'NOT',
    'ON',
    'OR',
    'OVER',
    'THEN',
    'USING',
    'WHEN',
])

function keywordCallsAsFunctions(tokens: Token[]): Token[] {
    return tokens.map((token, index) => {
        const next = tokens[index + 1]
        const isCall = KEYWORD_TOKEN_TYPES.has(token.type) && next?.text === '(' && String(next.type) === 'OPEN_PAREN'
        return isCall && !KEYWORDS_FOLLOWED_BY_PARENS.has(token.text.toUpperCase())
            ? { ...token, type: 'RESERVED_FUNCTION_NAME' as Token['type'] }
            : token
    })
}

const hogQLDialect: DialectOptions = {
    name: 'hogql',
    tokenizerOptions: {
        ...clickhouse.tokenizerOptions,
        reservedClauses: [
            'WITH',
            'FROM',
            'PREWHERE',
            'WHERE',
            'GROUP BY',
            'HAVING',
            'PARTITION BY',
            'ORDER BY',
            'LIMIT',
            'SETTINGS',
        ],
        reservedSetOperations: expandPhrases(['{UNION | INTERSECT | EXCEPT} [ALL | DISTINCT] [BY NAME]']),
        reservedJoins: expandPhrases([
            '[GLOBAL] [INNER | LEFT | RIGHT | FULL | CROSS] [OUTER] [SEMI | ANTI | ANY | ALL | ASOF] JOIN',
            '[GLOBAL] [SEMI | ANTI | ANY | ALL | ASOF] [INNER | LEFT | RIGHT | FULL] [OUTER] JOIN',
            '[LEFT] ARRAY JOIN',
        ]),
        reservedKeywordPhrases: expandPhrases(['WITH {TOTALS | TIES | CUBE | ROLLUP | FILL}']),
        identChars: { first: '$', rest: '$' },
        stringTypes: [{ quote: "''-qq-bs", prefixes: ['f', 'F'] }],
        lineCommentTypes: ['--', '//', '#'],
        paramTypes: { custom: [{ regex: String.raw`\{[^{}]*\}` }] },
        operators: [...(clickhouse.tokenizerOptions.operators ?? []), '??', '~', '=~', '!~', '~*', '=~*', '!~*'],
        postProcess: keywordCallsAsFunctions,
    },
    formatOptions: { onelineClauses: [], tabularOnelineClauses: [] },
}

function nestingDepth(query: string): number {
    let depth = 0
    let deepest = 0
    for (const char of query) {
        if (char === '(') {
            depth += 1
            deepest = Math.max(deepest, depth)
        } else if (char === ')') {
            depth = Math.max(0, depth - 1)
        }
    }
    return deepest
}

const TOKEN_CHARACTER = /[\w$'"`]/

function significantText(query: string): string {
    let text = ''
    let pendingSpace = false
    for (const char of query) {
        if (/\s/.test(char)) {
            pendingSpace = true
            continue
        }
        const previous = text[text.length - 1]
        if (pendingSpace && previous !== undefined && TOKEN_CHARACTER.test(previous) && TOKEN_CHARACTER.test(char)) {
            text += ' '
        }
        pendingSpace = false
        text += char
    }
    return text
}

const COMMENT = /(?:--|\/\/)[^\n]*|#(?![0-9])[^\n]*|\/\*[\s\S]*?\*\//g

function statementsOf(query: string): string[] {
    return splitQueries(query, { hogql: true })
        .map(({ query: statement }) => statement)
        .filter((statement) => statement.replace(COMMENT, '').trim() !== '')
}

async function verifyStatements(query: string, formatted: string): Promise<FormatHogQLFailure | null> {
    const statements = statementsOf(query)
    const formattedStatements = statementsOf(formatted)
    if (statements.length !== formattedStatements.length) {
        return 'unsupported'
    }
    let comparisons: SelectComparison[]
    try {
        const { compareSelectQueries } = await retryImport(
            () => import('scenes/data-warehouse/editor/hogqlParserWorkerManager')
        )
        comparisons = await Promise.all(
            statements.map((statement, index) => compareSelectQueries(statement, formattedStatements[index]))
        )
    } catch {
        return 'unverified'
    }
    if (comparisons.includes('unparsable')) {
        return 'unparsable'
    }
    return comparisons.every((comparison) => comparison === 'same') ? null : 'unsupported'
}

export async function formatHogQL(
    query: string,
    { tabWidth = 4, useTabs = false }: FormatHogQLOptions = {}
): Promise<FormatHogQLResult> {
    if (query.length > MAX_QUERY_LENGTH || nestingDepth(query) > MAX_NESTING_DEPTH) {
        return { formatted: null, failure: 'too_large' }
    }
    let formatted: string
    try {
        formatted = formatDialect(query, {
            dialect: hogQLDialect,
            tabWidth,
            useTabs,
            keywordCase: 'preserve',
            dataTypeCase: 'preserve',
            functionCase: 'preserve',
            identifierCase: 'preserve',
        })
    } catch {
        return { formatted: null, failure: 'unparsable' }
    }
    if (significantText(formatted) !== significantText(query)) {
        return { formatted: null, failure: 'unsupported' }
    }
    if (formatted === query) {
        return { formatted, failure: null }
    }
    const failure = await verifyStatements(query, formatted)
    return failure === null ? { formatted, failure: null } : { formatted: null, failure }
}
