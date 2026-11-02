import type { ApiKeyAccess, ApiToolLibrary } from '@posthog/mcp/src/cli/library-types'

import { defineCommand } from '@/core/command'
import type { Context } from '@/core/context'
import { plural } from '@/core/text'
import { ApiError } from '@/posthog/api'
import { apiConnection, groupSlug, unwrap } from '@/posthog/api-tools'

const TOP_SCOPES = 10

// A key can be limited to projects or to organizations. An organization limit needs the project's organization.
// Null when that can't be checked.
async function reachesProject(
    ctx: Context,
    library: ApiToolLibrary,
    access: ApiKeyAccess,
    projectId: string
): Promise<boolean | null> {
    if (access.scopedTeams.length > 0) {
        return access.scopedTeams.includes(Number(projectId))
    }
    if (access.scopedOrganizations.length === 0) {
        return true
    }
    try {
        const api = await ctx.posthog()
        const project = await api.get<{ organization: string }>(`/api/projects/${projectId}/`)
        return access.scopedOrganizations.includes(project.organization)
    } catch (error) {
        // Without project:read the lookup fails for any project, so a 403 says nothing about the limit.
        if (error instanceof ApiError && error.status === 403) {
            return library.missingScopes(access.scopes, ['project:read']).length === 0 ? false : null
        }
        if (error instanceof ApiError && error.status === 404) {
            return false
        }
        throw error
    }
}

export default defineCommand({
    description: 'Show what the personal API key can reach, and the scopes that would unlock more tools',
    notes: 'Each missing scope counts the tools it blocks. A tool can need more than one scope.',
    examples: ['hog api access', 'hog api access -o json'],

    async run({ ctx }) {
        const library = await ctx.apiTools()
        const connection = await apiConnection(ctx)
        const access = unwrap(await library.keyAccess(connection))
        const projectId = connection.projectId ?? ''
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
            projectAllowed: await reachesProject(ctx, library, access, projectId),
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
        if (result.projectAllowed === false) {
            const reach =
                result.scopedProjects.length > 0
                    ? `projects ${result.scopedProjects.join(', ')}`
                    : `organizations ${result.scopedOrganizations.join(', ')}`
            out.line(out.style(`The key can't reach project ${result.projectId}. It only reaches ${reach}.`, 'yellow'))
        }
        out.line(`Scopes: ${result.scopes.join(', ') || 'none'}`)
        out.line(`Usable tools: ${result.usable} of ${result.tools}`)
        if (result.missingScopes.length > 0) {
            out.line()
            out.table(
                ['missing scope', 'tools', 'groups'],
                result.missingScopes
                    .slice(0, TOP_SCOPES)
                    .map((entry) => [entry.scope, entry.tools, entry.groups.join(', ')])
            )
            const more = result.missingScopes.length - TOP_SCOPES
            if (more > 0) {
                out.line(out.style(`${plural(more, 'more missing scope')}. \`-o json\` lists them all.`, 'dim'))
            }
        }
    },
})
