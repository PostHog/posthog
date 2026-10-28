import { defineCommand } from '@/core/command'
import { findTool } from '@/posthog/api-tools'

export default defineCommand({
    description: "Print an API tool's input schema, or one field of it",
    args: {
        tool: { description: 'The tool name, as `hog api tools` lists it' },
        field: { description: 'A dotted path to a nested field, like filters.groups', optional: true },
    },
    examples: ['hog api schema feature-flag-get-all', 'hog api schema create-feature-flag filters.groups'],

    async run({ args, ctx }) {
        const library = await ctx.apiTools()
        return library.schema(findTool(library, args.tool).name, args.field)
    },
})
