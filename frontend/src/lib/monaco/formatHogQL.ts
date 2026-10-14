import { type DialectOptions, clickhouse, expandPhrases, formatDialect } from 'sql-formatter'

export interface FormatHogQLOptions {
    tabWidth?: number
    useTabs?: boolean
}

export type FormatHogQLFailure = 'too_large' | 'unparsable' | 'unsupported'

export type FormatHogQLResult = { formatted: string; failure: null } | { formatted: null; failure: FormatHogQLFailure }

// The formatter's parser slows down more than linearly with nesting depth: 1,000 nested parentheses
// take seconds on the UI thread, while 200 take well under 100 ms. Real queries stay far below both caps.
export const MAX_QUERY_LENGTH = 200_000
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

/**
 * Reflows the whitespace of a HogQL query. A query that is too large, does not parse, or would come
 * back with different tokens is refused with a failure reason, so the caller can leave the text as it is.
 */
export function formatHogQL(
    query: string,
    { tabWidth = 4, useTabs = false }: FormatHogQLOptions = {}
): FormatHogQLResult {
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
    // quote, so a format may only move whitespace between tokens.
    if (significantText(formatted) !== significantText(query)) {
        return { formatted: null, failure: 'unsupported' }
    }
    return { formatted, failure: null }
}
