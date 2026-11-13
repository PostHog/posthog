import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { EXIT_PENDING, EXIT_SUCCESS, EXIT_USAGE, HogError } from '@/core/errors'
import type { ColumnKind } from '@/core/output'
import { plural, shellQuote } from '@/core/text'
import { ApiError } from '@/posthog/api'
import { parseQueryId, type QueryId } from '@/posthog/ids'
import { startHogQL, waitForQuery, type HogQLResponse, type QueryState } from '@/posthog/query'

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

function resumeCommand(id: QueryId): string {
    return `hog query run --wait ${shellQuote(id, /^[\w-]+$/)}`
}

// Agent shells often stop a command after about two minutes. Waiting half of that leaves time for
// hog to start, for the last status request, and for the agent's other commands in the same call.
const AGENT_WAIT_MS = 60_000

type RunResult =
    | {
          status: 'done'
          columns: { name: string; type: string | null }[]
          rows: unknown[][]
          hasMore: boolean
          response: HogQLResponse
      }
    | { status: 'running'; queryId: string; next: string }

function isTransient(error: unknown): error is HogError {
    return (
        error instanceof HogError &&
        (error.code === 'network_error' || (error instanceof ApiError && (error.status === 429 || error.status >= 500)))
    )
}

function done(response: HogQLResponse): RunResult {
    return {
        status: 'done',
        columns: (response.columns ?? []).map((name, index) => ({
            name,
            type: response.types?.[index]?.[1] ?? null,
        })),
        rows: response.results,
        hasMore: response.hasMore === true,
        response,
    }
}

// A person whose stdout is a terminal and a CI job without an agent never run `--wait`, so they wait
// until the query ends. That holds when the query comes in on stdin, which leaves `ctx.prompts` and
// its spinner undefined, so the person gets one line on stderr instead.
async function follow(ctx: Context, id: QueryId): Promise<RunResult> {
    const { runtime } = ctx
    const waitsToTheEnd = ctx.mode.agent === undefined && (runtime.stdoutIsTTY || ctx.mode.isCI)
    const deadline = waitsToTheEnd ? undefined : runtime.now() + AGENT_WAIT_MS
    const spinner = ctx.prompts?.spinner(`Waiting for query ${id} to finish`)
    if (!spinner && waitsToTheEnd && runtime.stdoutIsTTY) {
        runtime.writeStderr(
            `Waiting for query ${id} to finish. After Ctrl-C, run ${resumeCommand(id)} to wait for it again.\n`
        )
    }
    let state: QueryState
    try {
        state = await waitForQuery(runtime, await ctx.posthog(), id, deadline)
    } catch (error) {
        spinner?.error("The query didn't finish")
        throw isTransient(error) ? error.withHint(`Run \`${resumeCommand(id)}\` to keep waiting for the query.`) : error
    }

    switch (state.state) {
        case 'running':
            return { status: 'running', queryId: id, next: resumeCommand(id) }
        case 'failed':
            spinner?.error("The query didn't finish")
            throw state.error
        case 'done':
            spinner?.stop('Query finished')
            return done(state.response)
    }
}

export default defineCommand({
    description: 'Run a HogQL query and print the results',
    args: {
        query: { description: 'The HogQL query to run, or - to read it from stdin', stdin: true, optional: true },
    },
    options: {
        wait: {
            type: 'string',
            placeholder: 'query-id',
            parse: parseQueryId,
            description: 'Wait for a query that is still running, by the `queryId` an earlier run returned',
        },
    },
    scopes: ['query:read'],
    notes: [
        'Prints a table in a terminal. Agents and pipes get one JSON object: `columns` with the name and ClickHouse type of each, `rows` as arrays in column order, and `hasMore`.',
        'When `hasMore` is true, PostHog cut the results off, and `hint` says how to get the rest. --raw prints the full response.',
        'Agents and pipes wait up to a minute. A query still running then returns `status` "running", its `queryId`, and in `next` the `hog query run --wait <query-id>` command that waits for it again. It exits with code 4.',
        'A person at a terminal and a CI job wait until the query finishes.',
    ].join('\n'),
    examples: [
        'hog query run "select event, count() from events group by event"',
        'cat query.sql | hog query run -',
        'hog query run --wait 0190f5b41d2a7000a8c13f6e2b9c7d10',
    ],

    async run({ args, options, ctx }): Promise<RunResult> {
        if (options.wait !== undefined) {
            if (args.query !== undefined) {
                throw new HogError(
                    'query_with_wait',
                    '`--wait` takes a query ID, not a query.',
                    `Run \`${resumeCommand(options.wait)}\` on its own, or \`hog query run <query>\` to run another query.`,
                    EXIT_USAGE
                )
            }
            return follow(ctx, options.wait)
        }

        if (args.query === undefined) {
            throw new HogError(
                'query_required',
                '`hog query run` needs a query.',
                'For example: `hog query run "select count() from events"`, or `-` to read it from stdin.',
                EXIT_USAGE
            )
        }

        let state: QueryState
        try {
            state = await startHogQL(await ctx.posthog(), args.query)
        } catch (error) {
            if (error instanceof ApiError && error.type === 'validation_error') {
                throw error.withHint('Run `hog query check` on the query to see where it fails.')
            }
            throw error
        }
        switch (state.state) {
            case 'running':
                return follow(ctx, state.id)
            case 'failed':
                throw state.error
            case 'done':
                return done(state.response)
        }
    },

    raw: (result) => (result.status === 'done' ? result.response : result),

    exitCode: (result) => (result.status === 'running' ? EXIT_PENDING : EXIT_SUCCESS),

    human({ result, out }) {
        if (result.status === 'running') {
            out.report({
                status: 'partial',
                result: 'The query is still running in PostHog',
                notes: [`Run ${out.style(result.next, 'bold')} to wait for the results.`],
            })
            return
        }
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
        if (result.status === 'running') {
            out.json(
                {
                    ...result,
                    hint: `The query is still running in PostHog. Run \`${result.next}\` to wait for the results.`,
                },
                { first: ['status', 'queryId', 'next'] }
            )
            return
        }
        const { columns, rows, hasMore } = result
        out.json(
            { columns, rows, hasMore, ...(hasMore ? { hint: moreRowsHint(rows.length) } : {}) },
            { first: ['columns', 'hasMore', 'hint'] }
        )
    },

    telemetry: ({ options, result }) =>
        result.status === 'running'
            ? { query_status: result.status, resumed: options.wait !== undefined }
            : {
                  query_status: result.status,
                  resumed: options.wait !== undefined,
                  row_count: result.rows.length,
                  column_count: result.columns.length,
                  has_more: result.hasMore,
              },
})
