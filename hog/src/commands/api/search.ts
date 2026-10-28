import { defineCommand } from '@/core/command'
import { findTool, grantedScopes, toolRow } from '@/posthog/api-tools'

import { toolTable } from './tools'

export default defineCommand({
    description: 'Find API tools by name, title or description',
    args: {
        pattern: { description: 'Words or a regular expression to match', variadic: true },
    },
    examples: ['hog api search feature flag', 'hog api search "^insight-"'],

    async run({ args, ctx }) {
        const library = await ctx.apiTools()
        const { names, truncated } = await library.search(args.pattern.join(' '))
        const granted = await grantedScopes(ctx, library)
        return { tools: names.map((name) => toolRow(library, findTool(library, name), granted)), truncated }
    },

    human({ result, out }) {
        toolTable(out, result.tools)
        if (result.truncated) {
            out.line(out.style('More tools match. Use more specific words to see them.', 'dim'))
        }
    },

    agent({ result, out }) {
        out.jsonLines(result.tools)
    },
})
