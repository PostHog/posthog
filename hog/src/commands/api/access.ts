import { defineCommand } from '@/core/command'
import { apiConnection, groupSlug, unwrap } from '@/posthog/api-tools'

export default defineCommand({
    description: 'Show what the personal API key can reach, and the scopes that would unlock more tools',
    notes: 'Each missing scope counts the tools it blocks. A tool can need more than one scope.',
    examples: ['hog api access', 'hog api access -o json'],

    async run({ ctx }) {
        const library = await ctx.apiTools()
        const connection = await apiConnection(ctx)
        const access = unwrap(await library.keyAccess(connection))
        const projectId = Number(connection.projectId)
        const blocked = new Map<string, { tools: number; groups: Set<string> }>()
        let usable = 0
        const tools = library.tools()
        for (const tool of tools) {
            const missing = library.missingScopes(access.scopes, tool.requiredScopes)
            usable += missing.length === 0 ? 1 : 0
            for (const scope of missing) {
                const entry = blocked.get(scope) ?? { tools: 0, groups: new Set<string>() }
                entry.tools += 1
                entry.groups.add(groupSlug(tool.group))
                blocked.set(scope, entry)
            }
        }
        return {
            scopes: access.scopes,
            projectId: connection.projectId ?? null,
            projectAllowed: access.scopedTeams.length === 0 || access.scopedTeams.includes(projectId),
            scopedProjects: access.scopedTeams,
            scopedOrganizations: access.scopedOrganizations,
            tools: tools.length,
            usable,
            missingScopes: [...blocked.entries()]
                .map(([scope, entry]) => ({ scope, tools: entry.tools, groups: [...entry.groups].sort() }))
                .sort((a, b) => b.tools - a.tools || a.scope.localeCompare(b.scope)),
        }
    },

    human({ result, out }) {
        if (!result.projectAllowed) {
            const projects = result.scopedProjects.join(', ')
            out.line(
                out.style(`The key can't reach project ${result.projectId}. It only reaches ${projects}.`, 'yellow')
            )
        }
        out.line(`Scopes: ${result.scopes.join(', ') || 'none'}`)
        out.line(`Usable tools: ${result.usable} of ${result.tools}`)
        if (result.missingScopes.length > 0) {
            out.line()
            out.table(
                ['missing scope', 'tools', 'groups'],
                result.missingScopes.map((entry) => [entry.scope, entry.tools, entry.groups.join(', ')])
            )
        }
    },
})
