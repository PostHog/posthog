/**
 * Shared helper for native tools that call PostHog HTTP endpoints **as the
 * connected user**. Auth resolves through the identity model (`posthog`
 * provider) — PostHog is not a special case. Unlinked → throws
 * `IdentityAuthRequiredError` (the dispatch wrapper relays an auth_required
 * link); unavailable → `posthog_credentials_unavailable`; non-2xx →
 * `posthog_api_error`. No host check: `ctx.posthogApiBaseUrl` is
 * platform-controlled, so the bearer can only reach the PostHog API host.
 */

import { type Credential, IdentityAuthRequiredError, type ToolContext, Type } from '@posthog/agent-shared'

/** The provider id native PostHog tools resolve their bearer under. */
export const POSTHOG_IDENTITY_PROVIDER = 'posthog'

function bearerFromCredential(cred: Credential): string {
    if (cred.kind === 'posthog_bearer' || cred.kind === 'oauth_bearer') {
        return cred.token
    }
    throw new Error('posthog_credentials_unavailable: resolved credential is not a bearer')
}

/**
 * Resolve the asker's PostHog bearer via the identity model. Prefers the
 * dispatch wrapper's pre-resolved credential; otherwise resolves live and maps
 * the `IdentityResolution` union onto throws the helper's callers understand.
 */
async function resolvePosthogBearer(ctx: ToolContext): Promise<string> {
    const pre = ctx.resolvedIdentities?.[POSTHOG_IDENTITY_PROVIDER]
    if (pre) {
        return bearerFromCredential(pre.credential)
    }
    if (!ctx.identity) {
        throw new Error('posthog_credentials_unavailable: no identity resolver wired in this session')
    }
    const res = await ctx.identity.resolve(POSTHOG_IDENTITY_PROVIDER)
    if (res.kind === 'link_required') {
        throw new IdentityAuthRequiredError(res.provider, res.authorizeUrl)
    }
    if (res.kind === 'unavailable') {
        throw new Error(`posthog_credentials_unavailable: ${res.reason}`)
    }
    return bearerFromCredential(res.credential)
}

export interface CallPosthogApiOpts {
    method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
    /** Path under the API root, e.g. `/api/projects/1/agent_applications/`. */
    path: string
    /** Query string (without leading `?`). */
    query?: Record<string, string | number | boolean | undefined>
    /** Body for non-GET requests. JSON-serialized automatically. */
    body?: unknown
}

export async function callPosthogApi<T = unknown>(ctx: ToolContext, opts: CallPosthogApiOpts): Promise<T> {
    const token = await resolvePosthogBearer(ctx)
    const qs = opts.query
        ? '?' +
          Object.entries(opts.query)
              .filter(([, v]) => v !== undefined)
              .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
              .join('&')
        : ''
    const baseUrl = ctx.posthogApiBaseUrl.replace(/\/+$/, '')
    const url = `${baseUrl}${opts.path}${qs}`
    const init: RequestInit = {
        method: opts.method,
        headers: {
            Authorization: `Bearer ${token}`,
            Accept: 'application/json',
            ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        },
        ...(opts.body !== undefined ? { body: JSON.stringify(opts.body) } : {}),
    }
    const res = await ctx.http.fetch(url, init)
    if (!res.ok) {
        const body = await res.text().catch(() => '')
        throw new Error(`posthog_api_error: ${res.status} ${body.slice(0, 400)}`)
    }
    if (res.status === 204) {
        return undefined as T
    }
    return (await res.json()) as T
}

/**
 * Build the project-scoped path prefix for an EXPLICIT project id supplied by
 * the agent (the `project_id` tool arg) — never inferred from the principal.
 *
 * The `@posthog/*` data tools act as the connected user against whichever
 * project the agent is operating on; the agent discovers that project from the
 * `get_context` client tool (the host tells it the user's current project) or,
 * when context is missing/ambiguous, from `@posthog/list-projects`. Standard
 * PostHog access control enforces that the user may actually touch the project.
 */
export function projectPath(projectId: number, suffix: string): string {
    return `/api/projects/${projectId}${suffix}`
}

/**
 * The explicit project (team) id that every project-scoped `@posthog/*` tool
 * takes as an argument. Spread/placed into each tool's `args: Type.Object({...})`
 * so the description (how to resolve it) stays identical across the surface.
 */
export const ProjectIdArg = Type.Number({
    description:
        "PostHog project (team) id to act in. Resolve it from the `get_context` client tool (the host reports the user's current project as `project_id`), or — when context is missing or ambiguous — call `@posthog/list-projects` and ask the user which project to use. Never guess.",
})
