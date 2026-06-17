/**
 * Shared helper for native tools that proxy PostHog HTTP endpoints **as
 * the connected user**.
 *
 * The credential broker (per-session, PG-backed, Fernet-encrypted) gives
 * us the user's OAuth bearer or PAT under target `posthog_api`. This
 * helper resolves it, makes the fetch, and translates the response into
 * a tool-friendly shape. All `@posthog/agent-applications-*` style
 * tools route through here so they share auth handling, error formatting,
 * and base-URL config.
 *
 * Failure semantics:
 *   - No broker / no `posthog_api` credential → throws
 *     `posthog_credentials_unavailable` (tool result becomes an error;
 *     the model adapts via agent.md degradation rules).
 *   - Non-2xx response → throws `posthog_api_error: <status> <body>`
 *     (response body trimmed to 400 chars for the model context).
 *   - Network error → propagates the original.
 *
 * Base URL is supplied via `ctx.posthogApiBaseUrl` — wired from
 * `config.posthogApiBaseUrl` at runner boot. Dev defaults to
 * `http://localhost:8010` via `PlatformConfigSchema`.
 */

import { type ToolContext, Type } from '@posthog/agent-shared'

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
    if (!ctx.credentials) {
        throw new Error('posthog_credentials_unavailable: credential broker not wired in this session')
    }
    const cred = await ctx.credentials.resolve('posthog_api')
    if (!cred || cred.kind !== 'posthog_bearer') {
        throw new Error('posthog_credentials_unavailable: no posthog_api credential for this session')
    }
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
            Authorization: `Bearer ${cred.token}`,
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
