import { type DialectOptions, clickhouse, expandPhrases, formatDialect } from 'sql-formatter'

export interface FormatHogQLOptions {
    tabWidth?: number
    useTabs?: boolean
}

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
// identifiers, `{placeholder}` expressions, `??`, the regex operators, `//` comments and HogQL's
// own join modifier order (`ASOF LEFT JOIN`). The clause list is limited to SELECT statements, so a
// column named `sample`, `format` or `values` does not start a clause of its own.
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
        stringTypes: ["''-qq-bs"],
        lineCommentTypes: ['--', '//', '#'],
        paramTypes: { custom: [{ regex: String.raw`\{[^{}]*\}` }] },
        operators: [...(clickhouse.tokenizerOptions.operators ?? []), '??', '~', '=~', '!~', '~*', '=~*', '!~*'],
        postProcess: keywordCallsAsFunctions,
    },
    formatOptions: { onelineClauses: [], tabularOnelineClauses: [] },
}

const withoutWhitespace = (query: string): string => query.replace(/\s+/g, '')

/**
 * Reflows the whitespace of a HogQL query. Returns null when the query does not parse, so the
 * caller can leave the text as it is.
 */
export function formatHogQL(query: string, { tabWidth = 4, useTabs = false }: FormatHogQLOptions = {}): string | null {
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
        return null
    }
    // HogQL identifiers and function names are case-sensitive, so a format must only move whitespace.
    return withoutWhitespace(formatted) === withoutWhitespace(query) ? formatted : null
}
