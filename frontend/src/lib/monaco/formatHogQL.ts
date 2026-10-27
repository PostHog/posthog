import { type DialectOptions, clickhouse, expandPhrases, formatDialect } from 'sql-formatter'

import type { SelectComparison } from 'scenes/data-warehouse/editor/hogqlAst'
import { compareSelectQueries } from 'scenes/data-warehouse/editor/hogqlParserWorkerManager'

import { splitQueries } from './multiQueryUtils'

export interface FormatHogQLOptions {
    tabWidth?: number
    useTabs?: boolean
}

export type FormatHogQLFailure = 'too_large' | 'unparsable' | 'unsupported' | 'unverified'

export type FormatHogQLResult = { formatted: string; failure: null } | { formatted: null; failure: FormatHogQLFailure }

// The formatter runs on the UI thread, and its cost grows faster than linearly with both the query
// length and the nesting depth. The caps keep one format short enough that the editor does not
// freeze, so a query above a cap is refused instead.
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

// HogQL exposes ClickHouse keywords and data types as functions: `any(x)`, `map(k, v)`, `left(s, n)`.
// The formatter puts a space between a keyword and `(`, so retype those calls as function names.
function keywordCallsAsFunctions(tokens: Token[]): Token[] {
    return tokens.map((token, index) => {
        const next = tokens[index + 1]
        const isCall = KEYWORD_TOKEN_TYPES.has(token.type) && next?.text === '(' && String(next.type) === 'OPEN_PAREN'
        return isCall && !KEYWORDS_FOLLOWED_BY_PARENS.has(token.text.toUpperCase())
            ? { ...token, type: 'RESERVED_FUNCTION_NAME' as Token['type'] }
            : token
    })
}

// HogQL is ClickHouse SQL with extra syntax that the ClickHouse dialect rejects or splits: `$` in
// identifiers, `{placeholder}` expressions, `f'template {strings}'`, `??`, the regex operators,
// `//` comments and HogQL's own join modifier order (`ASOF LEFT JOIN`). The clause list is limited
// to SELECT statements, so a column named `sample`, `format` or `values` does not start a clause.
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
        // Without these, `WITH` opens a new clause in the middle of `GROUP BY a WITH TOTALS`.
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

// Whitespace between two of these characters separates tokens (`select event`, `f'x'` against
// `f 'x'`), so it stays as one space. Whitespace next to anything else is layout and is dropped.
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

// HogQL comments. A `#` followed by a digit is a positional reference, as in `ORDER BY #1`.
const COMMENT = /(?:--|\/\/)[^\n]*|#(?![0-9])[^\n]*|\/\*[\s\S]*?\*\//g

// The parser reads one statement at a time. A part that holds only comments, such as a query that
// is commented out after the last semicolon, has no statement to parse.
function statementsOf(query: string): string[] {
    return splitQueries(query)
        .map(({ query: statement }) => statement)
        .filter((statement) => statement.replace(COMMENT, '').trim() !== '')
}

/** Parses each statement before and after the format, and returns null only when no meaning changed. */
async function verifyStatements(query: string, formatted: string): Promise<FormatHogQLFailure | null> {
    const statements = statementsOf(query)
    const formattedStatements = statementsOf(formatted)
    if (statements.length !== formattedStatements.length) {
        return 'unsupported'
    }
    let comparisons: SelectComparison[]
    try {
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

/**
 * Reflows the whitespace of a HogQL query. When the query cannot be formatted safely, the result
 * carries a failure reason instead, so the caller can leave the text as it is.
 */
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
    // HogQL identifiers and function names are case-sensitive and a string prefix must touch its
    // quote, so a format may only move whitespace between tokens. The parser skips comments, so this
    // check is also the one that keeps every comment intact.
    if (significantText(formatted) !== significantText(query)) {
        return { formatted: null, failure: 'unsupported' }
    }
    if (formatted === query) {
        return { formatted, failure: null }
    }
    // The dialect only approximates the HogQL lexer. It can split a token that it does not know, such
    // as the `/>` of a HogQLX tag, or misread where a string ends and collapse the spaces in it. The
    // text check above cannot see either change, but both change what the HogQL parser returns.
    const failure = await verifyStatements(query, formatted)
    return failure === null ? { formatted, failure: null } : { formatted: null, failure }
}
