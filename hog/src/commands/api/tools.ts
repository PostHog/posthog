import { defineCommand } from '@/core/command'
import type { Output } from '@/core/output'
import { findGroup, grantedScopes, toolRow, type ToolRow } from '@/posthog/api-tools'

export function toolTable(out: Output, rows: readonly ToolRow[]): void {
    const known = rows.some((row) => row.usable !== null)
    out.table(
        known ? ['tool', 'kind', 'usable', 'summary'] : ['tool', 'kind', 'summary'],
        rows.map((row) => (known ? [row.name, row.kind, row.usable, row.summary] : [row.name, row.kind, row.summary]))
    )
}

export default defineCommand({
    description: 'List the API tools, or the tools in one group',
    args: {
        group: { description: 'A group from `hog api groups`', optional: true },
    },
    notes: 'Each tool shows whether it reads, writes or deletes, and which scopes the personal API key is missing for it.',
    examples: ['hog api tools feature-flags', 'hog api tools -o json'],

    async run({ args, ctx }) {
        const library = await ctx.apiTools()
        const tools = args.group ? findGroup(library, args.group).tools : library.tools()
        const granted = await grantedScopes(ctx, library)
        return tools.map((tool) => toolRow(library, tool, granted))
    },

    human({ result, out }) {
        toolTable(out, result)
        out.line(out.style('Run `hog api info <tool>` to see what a tool does and the input it takes.', 'dim'))
    },

    agent({ result, out }) {
        out.jsonLines(result)
    },
})
