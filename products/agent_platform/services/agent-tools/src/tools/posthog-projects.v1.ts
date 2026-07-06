import { defineNativeTool, Type } from '@posthog/agent-shared'

import { callPosthogApi } from './_posthog-api'

/**
 * Minimal slice of `/api/users/@me/` we need to enumerate the projects the
 * connected user can act in. The current `organization` always embeds its
 * `projects`; `organizations[]` (the membership list) may also embed them, so
 * we read both and dedupe — that covers the multi-org user without an extra
 * call per org.
 */
interface MeProject {
    id: number
    name: string
}
interface MeOrganization {
    id: string
    name: string
    projects?: MeProject[]
}
interface MeResponse {
    organization?: MeOrganization | null
    organizations?: MeOrganization[] | null
}

/**
 * `@posthog/list-projects` — the project picker for tenant-neutral agents.
 *
 * The `@posthog/*` data tools each take an explicit `project_id`; an agent
 * normally learns it from the host's `get_context` client tool. When there is
 * no host context (non-console clients) or the user's intent is ambiguous, the
 * agent calls this to enumerate the projects the user can reach, presents them,
 * and asks which to use — then threads the chosen id into the other tools.
 *
 * Returns ONLY `{ id, name, organization }` so a long project list can't blow
 * up the model's context.
 */
export const posthogListProjectsV1 = defineNativeTool({
    id: '@posthog/list-projects',
    description:
        "List the PostHog projects the connected user can access — id, name, and organization only. Use to resolve which project to act in when `get_context` didn't supply a `project_id` or the user's intent is ambiguous: present the list, ask the user to choose, then pass the chosen `project_id` to the other `@posthog/*` tools. Don't guess a project id.",
    args: Type.Object({}),
    returns: Type.Object({
        projects: Type.Array(
            Type.Object({
                id: Type.Number(),
                name: Type.String(),
                organization: Type.String(),
            })
        ),
    }),
    requires: { provider: { id: 'posthog', scopes: [] } },
    cost_hint: 'cheap',
    async run(_args, ctx) {
        const me = await callPosthogApi<MeResponse>(ctx, { method: 'GET', path: '/api/users/@me/' })
        const orgs = [me.organization, ...(me.organizations ?? [])].filter((o): o is MeOrganization => o != null)
        const seen = new Set<number>()
        const projects: { id: number; name: string; organization: string }[] = []
        for (const org of orgs) {
            for (const p of org.projects ?? []) {
                if (seen.has(p.id)) {
                    continue
                }
                seen.add(p.id)
                projects.push({ id: p.id, name: p.name, organization: org.name })
            }
        }
        ctx.log('info', 'projects.listed', { count: projects.length })
        return { projects }
    },
})
