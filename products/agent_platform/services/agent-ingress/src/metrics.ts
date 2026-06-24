/**
 * Prometheus metrics for the agent-ingress (HTTP front door).
 *
 * Declared against the shared registry. Deliberately lean — the shared
 * `agent_http_request_duration_seconds` histogram (recorded by the middleware
 * in `routing/http-utils.ts`) already covers per-route latency + status, which
 * subsumes generic request-rate, error-rate, and auth-rejection (401/403)
 * tracking. These two add the signals HTTP status alone can't express:
 *
 *   - intake SHAPE (a 200 doesn't say whether it created a session, resumed
 *     one, or idempotently deduped) attributed per trigger; and
 *   - open long-lived SSE streams, which never "finish" so a duration
 *     histogram can't see them — a climbing gauge means leaked subscriptions.
 */

import { Counter, Gauge } from '@posthog/agent-shared'

/**
 * Trigger intake outcomes. `outcome` ∈ created | resumed | elevation_required
 * | error (mirrors `EnqueueOutcome.kind`). The demand signal that feeds the
 * runner queue — break down by `trigger` to see chat vs slack vs webhook vs
 * mcp load and the new-vs-resume mix.
 */
export const enqueueTotal = new Counter({
    name: 'agent_ingress_enqueue_total',
    help: 'Trigger intake outcomes by trigger type (created/resumed/elevation_required/error).',
    labelNames: ['trigger', 'outcome'],
})

/**
 * Currently-open long-lived SSE streams, by transport (chat `/listen`, mcp).
 * These hold a Redis bus subscription + an open socket for the session's
 * lifetime; a value that climbs without bound (vs. connected clients) is a
 * leaked-subscription / stuck-stream signal.
 */
export const activeStreams = new Gauge({
    name: 'agent_ingress_active_streams',
    help: 'Open long-lived SSE streams by transport (chat/mcp). Climbing unbounded = leaked subscriptions.',
    labelNames: ['transport'],
})
