import { format as sqlFormat, FormatOptionsWithLanguage } from 'sql-formatter'

// HogQL is built on ClickHouse SQL — the clickhouse dialect handles its array literals,
// lambda arrows, backtick-quoted identifiers, and function names without injecting
// spurious whitespace.
//
// - `keywordCase: 'preserve'` because ClickHouse's reserved word list includes column
//   names common in HogQL (`event`, `events`, `user`) — uppercasing them would
//   silently mangle queries that select those columns.
// - `paramTypes.custom` teaches the tokenizer that `$identifier` is a property
//   accessor (e.g. `properties.$current_url`), not a parameter placeholder.
const DEFAULT_OPTIONS: FormatOptionsWithLanguage = {
    language: 'clickhouse',
    keywordCase: 'preserve',
    indentStyle: 'standard',
    tabWidth: 4,
    useTabs: false,
    linesBetweenQueries: 2,
    paramTypes: {
        custom: [{ regex: String.raw`\$[a-zA-Z_][a-zA-Z0-9_]*` }],
    },
}

export function formatSQL(query: string, options: FormatOptionsWithLanguage = {}): string {
    if (!query || !query.trim()) {
        return query
    }
    return sqlFormat(query, { ...DEFAULT_OPTIONS, ...options })
}
