/**
 * Tenant-safe session fetch for trigger handlers.
 *
 * A `session_id` on a request is client-supplied, and for public agents every
 * principal is `{ kind: 'anonymous' }` — so `principalsMatch` alone can't tell
 * agent A's session from agent B's. Every handler that loads a session by id
 * must therefore scope it to the agent the request resolved to. That check is
 * easy to forget and fails open (a found row is returned regardless of tenant),
 * which is exactly the gap that bit `/send` `/listen` `/cancel`
 * `/client_tool_result`, `/mcp/stream`, and the Slack interactivity handler.
 *
 * `getOwnedSession` is the single sanctioned way to do it: it routes through
 * `queue.getForApplication`, which scopes in SQL, and returns `null` on both
 * "no such session" and "belongs to another agent" so callers can't
 * distinguish the two (no cross-tenant existence leak). A semgrep rule
 * (`.semgrep/rules/devex/agent-ingress-scoped-session-fetch.yaml`) forbids raw
 * `queue.get(...)` elsewhere in `triggers/` so a new handler can't reintroduce
 * the gap.
 */

import type { AgentSession } from '@posthog/agent-shared'

import type { RouteCtx } from './types'

export async function getOwnedSession(ctx: RouteCtx, sessionId: string): Promise<AgentSession | null> {
    return ctx.deps.queue.getForApplication(sessionId, ctx.resolved.application.id)
}
