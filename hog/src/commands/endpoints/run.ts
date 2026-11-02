import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { plural } from '@/core/text'
import { listInsightVariables } from '@/endpoints/api'
import { readEndpointFiles } from '@/endpoints/files'
import { ApiError, type PostHogApi } from '@/posthog/api'

interface RunResponse {
    columns?: string[] | null
    results?: unknown[] | null
    hasMore?: boolean | null
}

// HogQL finds a variable by its project ID, so a file's variables must exist in the project. A
// value left out uses the variable's default.
async function queryVariables(api: PostHogApi, values: Map<string, unknown>): Promise<Record<string, unknown>> {
    const known = new Map((await listInsightVariables(api)).map((variable) => [variable.code_name, variable]))
    const missing = [...values.keys()].filter((name) => !known.has(name))
    if (missing.length > 0) {
        throw new HogError(
            'unknown_variable',
            `The project has no variable named ${missing.join(', ')}.`,
            '`hog endpoints push` creates the variables a file defines.'
        )
    }
    return Object.fromEntries(
        [...values].map(([name, value]) => {
            const { id } = known.get(name)!
            const entry = { variableId: id, code_name: name, ...(value === undefined ? {} : { value }) }
            // Without `isNull`, PostHog replaces a null value with the project's default.
            return [id, value === null ? { ...entry, isNull: true } : entry]
        })
    )
}

function parseVariables(pairs: readonly string[]): Record<string, string> {
    return Object.fromEntries(
        pairs.map((pair) => {
            const separator = pair.indexOf('=')
            if (separator <= 0) {
                throw new HogError(
                    'invalid_variable',
                    `--var ${pair} isn't name=value.`,
                    'Pass each variable as --var name=value.',
                    EXIT_USAGE
                )
            }
            return [pair.slice(0, separator), pair.slice(separator + 1)]
        })
    )
}

export default defineCommand({
    description: 'Run an endpoint, or the query in a local endpoint file, and print the results',
    args: { name: { description: 'The endpoint to run', optional: true } },
    options: {
        file: {
            type: 'string',
            short: 'f',
            placeholder: 'path',
            description: 'Run the query in this endpoint file without creating the endpoint',
        },
        var: {
            type: 'string',
            short: 'v',
            placeholder: 'name=value',
            multiple: true,
            description: 'A variable value for the query. Repeat it for each variable',
        },
    },
    scopes: ['endpoint:read', 'query:read', 'insight_variable:read'],
    notes: 'Prints a table in a terminal, and one JSON array per row for agents and pipes. --raw prints the full response.',
    examples: [
        'hog endpoints run daily-signups',
        'hog endpoints run events-by-type --var event_type=$pageview',
        'hog endpoints run --file endpoints/daily-signups.yaml',
    ],

    async run({ args, options, ctx }): Promise<RunResponse> {
        if ((args.name === undefined) === (options.file === undefined)) {
            throw new HogError(
                'usage_error',
                'Pass an endpoint name or --file, but not both.',
                'Run `hog endpoints list` to see the endpoint names.',
                EXIT_USAGE
            )
        }
        const variables = parseVariables(options.var ?? [])
        const withVariables = Object.keys(variables).length > 0 ? { variables } : {}
        const api = await ctx.posthog()

        if (options.file !== undefined) {
            const { endpoints, problems } = await readEndpointFiles(ctx.runtime, [options.file])
            const [local] = endpoints
            if (!local) {
                const [problem] = problems
                throw new HogError(
                    'invalid_endpoint_file',
                    `${problem?.path ?? options.file}: ${problem?.message ?? 'not an endpoint file'}`
                )
            }
            const query: Record<string, unknown> = local.file.query_definition ?? {
                kind: 'HogQLQuery',
                query: local.file.query,
            }
            const values = new Map<string, unknown>()
            for (const variable of local.file.variables ?? []) {
                values.set(variable.name, variable.default)
            }
            for (const [name, value] of Object.entries(variables)) {
                values.set(name, value)
            }
            if (values.size > 0) {
                query.variables = await queryVariables(api, values)
            }
            return api.post<RunResponse>('query/', { query, name: 'endpoints_cli', refresh: 'blocking' })
        }

        try {
            return await api.post<RunResponse>(`endpoints/${encodeURIComponent(args.name!)}/run/`, withVariables)
        } catch (error) {
            if (error instanceof ApiError && error.status === 404) {
                throw error.withHint(
                    `Check that ${args.name} is in \`hog endpoints list\` and active. Inactive endpoints don't run.`
                )
            }
            throw error
        }
    },

    human({ result, out }) {
        const rows = (result.results ?? []) as unknown[][]
        if (result.columns && rows.every(Array.isArray)) {
            out.table(result.columns, rows)
            const count = plural(rows.length, 'row')
            out.line(out.style(result.hasMore ? `${count}, more available` : count, 'dim'))
            return
        }
        out.json(result.results ?? result)
    },

    agent({ result, out }) {
        out.jsonLines(result.results ?? [])
    },

    telemetry: ({ result, args, options }) => ({
        source: args.name === undefined ? 'file' : 'endpoint',
        variable_count: options.var?.length ?? 0,
        row_count: result.results?.length ?? 0,
    }),
})
