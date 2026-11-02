import { defineCommand } from '@/core/command'
import { printDiagnostics, type Diagnostics } from '@/core/diagnostics'

interface MetadataResponse extends Diagnostics {
    isValid?: boolean | null
}

export default defineCommand({
    description: 'Check the syntax and types of a HogQL query without running it',
    args: {
        query: { description: 'The HogQL query to check, or - to read it from stdin', stdin: true },
    },
    scopes: ['query:read'],
    notes: 'Exits with code 1 when the query has errors, so scripts and agents can branch on it.',
    examples: ['hog query check "select event from events"'],

    async run({ args, ctx }) {
        const api = await ctx.posthog()
        const response = await api.post<MetadataResponse>('query', {
            query: { kind: 'HogQLMetadata', language: 'hogQL', query: args.query },
        })
        return { query: args.query, response }
    },

    human({ result, out }) {
        printDiagnostics(out, result.query, result.response)
    },

    agent({ result, out }) {
        out.json(result.response)
    },

    exitCode: ({ response }) => ((response.errors ?? []).length > 0 ? 1 : 0),
})
