import { defineCommand } from '@/core/command'
import type { ColumnKind } from '@/core/output'
import { plural } from '@/core/text'
import { ApiError } from '@/posthog/api'
import { runHogQL, type HogQLResponse } from '@/posthog/query'

// ClickHouse returns 64-bit integers as JSON numbers and dates as strings, so the declared type
// colors a column better than its values do.
function kindOf(clickhouseType: string | null): ColumnKind | undefined {
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

function moreRowsHint(count: number): string {
    return `Only the first ${plural(count, 'row')} came back. Add a LIMIT to the query to get more, up to 50000, or filter or aggregate it to need fewer.`
}

export default defineCommand({
    description: 'Run a HogQL query and print the results',
    args: {
        query: { description: 'The HogQL query to run, or - to read it from stdin', stdin: true },
    },
    scopes: ['query:read'],
    notes: [
        'Prints a table in a terminal. Agents and pipes get one JSON object: `columns` with the name and ClickHouse type of each, `rows` as arrays in column order, and `hasMore`.',
        'When `hasMore` is true, PostHog cut the results off, and `hint` says how to get the rest. --raw prints the full response.',
    ].join('\n'),
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
            columns: (response.columns ?? []).map((name, index) => ({
                name,
                type: response.types?.[index]?.[1] ?? null,
            })),
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
        if (result.hasMore) {
            out.notes({ notes: [moreRowsHint(result.rows.length)] })
        }
    },

    // Rows stay arrays because HogQL can return two columns with the same name, as in
    // `select a.id, b.id`, and an object keyed by column name would keep only one of them.
    agent({ result, out }) {
        const { columns, rows, hasMore } = result
        out.json(
            { columns, rows, hasMore, ...(hasMore ? { hint: moreRowsHint(rows.length) } : {}) },
            { first: ['columns', 'hasMore', 'hint'] }
        )
    },

    telemetry: ({ result }) => ({
        row_count: result.rows.length,
        column_count: result.columns.length,
        has_more: result.hasMore,
    }),
})
