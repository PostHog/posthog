import { defineCommand } from '@/core/command'
import type { ColumnKind } from '@/core/output'
import { plural } from '@/core/text'
import { ApiError } from '@/posthog/api'
import { runHogQL, type HogQLResponse } from '@/posthog/query'

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
        let response: HogQLResponse
        try {
            response = await runHogQL(await ctx.posthog(), args.query)
        } catch (error) {
            if (error instanceof ApiError && error.type === 'validation_error') {
                throw error.withHint('Run `hog query check` on the query to see where it fails.')
            }
            throw error
        }
        return {
            columns: (response.columns ?? []).map((name, index) => ({ name, type: response.types?.[index]?.[1] })),
            rows: response.results,
            hasMore: response.hasMore === true,
            response,
        }
    },

    raw: (result) => result.response,

    human({ result, out }) {
        out.table(
            result.columns.map((column) => ({ name: column.name, kind: kindOf(column.type) })),
            result.rows
        )
        const count = plural(result.rows.length, 'row')
        out.line(out.style(result.hasMore ? `${count}, more available` : count, 'dim'))
    },

    agent({ result, out }) {
        out.jsonLines(result.rows)
    },

    telemetry: ({ result }) => ({
        row_count: result.rows.length,
        column_count: result.columns.length,
        has_more: result.hasMore,
    }),
})
