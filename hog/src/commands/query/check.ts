import { defineCommand } from '../../core/command'
import type { Output, Style } from '../../core/output'
import { plural } from '../../core/text'

interface MetadataNotice {
    message: string
    start?: number
    end?: number
}

interface MetadataResponse {
    isValid?: boolean | null
    errors?: MetadataNotice[] | null
    warnings?: MetadataNotice[] | null
    notices?: MetadataNotice[] | null
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
        printProblems(out, result.query, result.response)
    },

    agent({ result, out }) {
        out.json(result.response)
    },

    exitCode: ({ response }) => ((response.errors ?? []).length > 0 ? 1 : 0),
})

function printProblems(out: Output, query: string, response: MetadataResponse): void {
    const groups: { label: string; style: Style; items: MetadataNotice[] }[] = [
        { label: 'error', style: 'red', items: response.errors ?? [] },
        { label: 'warning', style: 'yellow', items: response.warnings ?? [] },
        { label: 'notice', style: 'cyan', items: response.notices ?? [] },
    ]
    for (const group of groups) {
        for (const item of group.items) {
            out.line(`${out.style(group.label, group.style, 'bold')}: ${item.message}`)
            if (item.start === undefined) {
                continue
            }
            const { line, column, text } = locate(query, item.start)
            const width = Math.max(1, Math.min((item.end ?? item.start + 1) - item.start, text.length - column + 1))
            const gutter = `${line} | `
            out.line(out.style(`  --> line ${line}, column ${column}`, 'dim'))
            out.line(`  ${out.style(gutter, 'dim')}${text}`)
            out.line(`  ${' '.repeat(gutter.length + column - 1)}${out.style('^'.repeat(width), group.style)}`)
        }
    }
    const errors = response.errors?.length ?? 0
    const summary = groups.map((group) => plural(group.items.length, group.label)).join(', ')
    out.line(errors === 0 ? out.style(`Query is valid (${summary})`, 'green') : out.style(summary, 'red'))
}

// Converts a character offset into a 1-based line and column, and returns that line's text.
function locate(source: string, offset: number): { line: number; column: number; text: string } {
    const before = source.slice(0, offset).split('\n')
    const line = before.length
    const column = (before.at(-1)?.length ?? 0) + 1
    return { line, column, text: source.split('\n')[line - 1] ?? '' }
}
