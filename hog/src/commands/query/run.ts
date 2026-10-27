import { defineCommand } from '../../core/command'
import { plural } from '../../core/text'
import { ApiError } from '../../posthog/api'

interface QueryResponse {
    columns?: string[] | null
    results?: unknown[][] | null
    hasMore?: boolean | null
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
        out.table(result.columns ?? [], rows)
        const count = plural(rows.length, 'row')
        out.line(out.style(result.hasMore ? `${count}, more available` : count, 'dim'))
    },

    agent({ result, out }) {
        out.jsonLines(result.results ?? [])
    },
})
