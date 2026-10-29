import { defineCommand } from '@/core/command'
import type { ColumnKind } from '@/core/output'
import { plural } from '@/core/text'
import { ApiError } from '@/posthog/api'

interface QueryResponse {
    columns?: string[] | null
    results?: unknown[][] | null
    types?: [string, string][] | null
    hasMore?: boolean | null
}

// ClickHouse returns 64-bit integers as JSON numbers and dates as strings, so the declared type
// colors a column better than its values do.
function kindOf(clickhouseType: string | undefined): ColumnKind | undefined {
    // Only the prefix matters, so wrappers like LowCardinality(Nullable(String)) drop their opening half.
    const base = clickhouseType?.replace(/^((Nullable|LowCardinality)\()+/, '')
    if (!base) {
        return undefined
    }
    const kinds: [RegExp, ColumnKind][] = [
        [/^(U?Int|Float|Decimal)/, 'number'],
        [/^Date/, 'date'],
        [/^Bool/, 'boolean'],
        [/^(Array|Map|Tuple|JSON|Object)/, 'json'],
    ]
    return kinds.find(([pattern]) => pattern.test(base))?.[1] ?? 'string'
}

export default defineCommand({
    description: 'Run a HogQL query and print the results',
    args: {
        query: { description: 'The HogQL query to run, or - to read it from stdin', stdin: true },
    },
    scopes: ['query:read'],
    notes: 'Prints a table in a terminal, and one JSON array per row for agents and pipes. --raw prints the full response.',
    examples: ['hog query run "select event, count() from events group by event"', 'cat query.sql | hog query run -'],

    async run({ args, ctx }) {
        const api = await ctx.posthog()
        try {
            return await api.post<QueryResponse>('query', {
                query: { kind: 'HogQLQuery', query: args.query },
                refresh: 'blocking',
            })
        } catch (error) {
            if (error instanceof ApiError && error.type === 'validation_error') {
                throw error.withHint('Run `hog query check` on the query to see where it fails.')
            }
            throw error
        }
    },

    human({ result, out }) {
        const rows = result.results ?? []
        out.table(
            (result.columns ?? []).map((name, index) => ({ name, kind: kindOf(result.types?.[index]?.[1]) })),
            rows
        )
        const count = plural(rows.length, 'row')
        out.line(out.style(result.hasMore ? `${count}, more available` : count, 'dim'))
    },

    agent({ result, out }) {
        out.jsonLines(result.results ?? [])
    },

    telemetry: ({ result }) => ({
        row_count: result.results?.length ?? 0,
        column_count: result.columns?.length ?? 0,
        has_more: result.hasMore === true,
    }),
})
