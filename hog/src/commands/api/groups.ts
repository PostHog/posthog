import { defineCommand } from '@/core/command'
import { grantedScopes, groupTools } from '@/posthog/api-tools'

export default defineCommand({
    description: 'List the groups of API tools, with how many each holds',
    notes: 'With credentials, `usable` counts the tools the personal API key has the scopes for.',
    examples: ['hog api groups', 'hog api tools feature-flags'],

    async run({ ctx }) {
        const library = await ctx.apiTools()
        const granted = await grantedScopes(ctx, library)
        return groupTools(library.tools()).map((group) => ({
            group: group.slug,
            name: group.name,
            tools: group.tools.length,
            usable: granted
                ? group.tools.filter((tool) => library.missingScopes(granted, tool.requiredScopes).length === 0).length
                : null,
        }))
    },

    human({ result, out }) {
        const known = result.some((group) => group.usable !== null)
        out.table(
            known ? ['group', 'tools', 'usable'] : ['group', 'tools'],
            result.map((group) => (known ? [group.group, group.tools, group.usable] : [group.group, group.tools]))
        )
        out.line(out.style('Run `hog api tools <group>` to list the tools in a group.', 'dim'))
    },

    agent({ result, out }) {
        out.jsonLines(result)
    },
})
