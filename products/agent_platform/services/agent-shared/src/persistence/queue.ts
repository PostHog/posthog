/**
 * Session queue contract. Postgres-backed everywhere — one row per
 * AgentSession, claimable via `SELECT FOR UPDATE SKIP LOCKED`. The PG impl
 * lives in `pg-queue.ts`. There is no in-memory variant; tests run against
 * the real test DB so claim semantics, indexes, and constraints are exercised.
 */

import {
    AgentSession,
    ConversationMessage,
    PendingElevationRequest,
    SessionAclEntry,
    SessionPrincipal,
    SessionUsageTotal,
} from '../spec/spec'

/** Input to the atomic elevation-decision transition (`decideElevationRequest`). */
export interface DecideElevationInput {
    requestId: string
    decision: 'grant' | 'decline'
    /** The principal making the decision (the session owner clicking grant/decline). */
    decidedBy: SessionPrincipal
    /** grant only: expiry on the new ACL entry (ms from now). null/omitted = no expiry. */
    expiresInMs?: number | null
    reason?: string | null
}

/**
 * Result of `decideElevationRequest`. `applied: true` means THIS call performed
 * the transition; `applied: false` means it was a no-op (the request was already
 * decided by a concurrent/replayed call, or doesn't exist) — the caller must not
 * treat a no-op as a fresh decision.
 */
export type DecideElevationResult =
    | { applied: true; decision: 'grant'; request: PendingElevationRequest; aclEntry: SessionAclEntry }
    | { applied: true; decision: 'decline'; request: PendingElevationRequest }
    | { applied: false; reason: 'not_found' | 'not_pending'; request: PendingElevationRequest | null }

/** Shape returned by both `aggregateForApplication` and `aggregateForTeam`. */
export interface AggregateStats {
    /** Sessions currently in a live state (queued / running / waiting). */
    liveCount: number
    /** Sessions created within the `since` window — all states. */
    sessionsInWindowCount: number
    /** Sum of `usage_total.cost_total` across sessions in the window. */
    spendInWindowUsd: number
    /** ISO timestamp of the most recent session update — null if none. */
    lastActivityAt: string | null
    /** Sessions in `failed` state created within the window. */
    failedInWindowCount: number
}

/** Live (non-terminal) session states. `completed`/`closed`/`cancelled`/`failed` are terminal. */
export const LIVE_SESSION_STATES: AgentSession['state'][] = ['queued', 'running']

export interface ListSessionsOpts {
    limit?: number
    offset?: number
    /** Filter to one or more session states (e.g. ['completed','failed']). */
    states?: AgentSession['state'][]
    /** Filter to a specific revision id within the application. */
    revisionId?: string
    /**
     * Filter to sessions started by one agent user. Matches the
     * `agent_user_id` stamped on the session principal (set today only for
     * slack-trigger sessions — other kinds don't carry it yet, so they won't
     * match).
     */
    agentUserId?: string
    /** ISO datetime — only return sessions with created_at >= this. */
    createdAfter?: string
    /** ISO datetime — only return sessions with created_at <= this. */
    createdBefore?: string
    /** Case-insensitive substring over id, external_key, and the conversation digest. */
    search?: string
}

/**
 * Lightweight list row — every summary column except the heavy `conversation`
 * JSONB. `turns` and `search_text` come off persisted columns, so listing never
 * detoasts a transcript.
 */
export interface SessionSummary {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    idempotency_key: string | null
    trigger_metadata: Record<string, unknown> | null
    state: AgentSession['state']
    principal: AgentSession['principal']
    usage_total: SessionUsageTotal
    retry_count: number
    turns: number
    search_text: string | null
    created_at: string
    updated_at: string
}

/**
 * Narrow capability the runner needs to read + grow `pending_inputs` mid-loop
 * without taking the whole `SessionQueue` dependency (and without the runner
 * caching a stale in-memory copy of the column). `PgSessionQueue` satisfies
 * this structurally — pass the queue directly.
 */
export interface SessionInputsStore {
    drainPendingInputs(sessionId: string): Promise<ConversationMessage[]>
    appendPendingInput(sessionId: string, msg: ConversationMessage): Promise<void>
}

/**
 * Full session-persistence surface. Extends `SessionInputsStore` so the
 * narrow per-input methods (`appendPendingInput`, `drainPendingInputs`)
 * are documented there; consumers that only need those two should depend
 * on `SessionInputsStore` instead of pulling the whole queue.
 */
export interface SessionQueue extends SessionInputsStore {
    enqueue(session: AgentSession): Promise<void>
    /** Block-claim the next session, returning null if none available within timeoutMs. */
    claim(timeoutMs: number): Promise<AgentSession | null>
    update(sessionId: string, patch: Partial<AgentSession>): Promise<void>
    /** Append directly into `conversation` (runner-side use only). */
    appendConversation(sessionId: string, msg: ConversationMessage): Promise<void>
    /**
     * Append a pending elevation request to the session. Used by ingress when
     * `requireAclAccess` rejects an incoming principal — the rejected message
     * is preserved so a future grant can replay it.
     */
    appendPendingElevationRequest(sessionId: string, req: PendingElevationRequest): Promise<void>
    /**
     * Atomically decide a pending elevation request under a row lock. Re-reads
     * the request state inside the transaction (NOT from a caller snapshot) so
     * a concurrent or replayed decision can't apply twice — only the first
     * caller transitions the request and (for a grant) replays the proposed
     * message into `pending_inputs` + re-queues. Returns `applied: false` when
     * the request was already decided or is missing.
     */
    decideElevationRequest(sessionId: string, input: DecideElevationInput): Promise<DecideElevationResult>
    get(sessionId: string): Promise<AgentSession | null>
    /**
     * Like `get`, but scoped to one application — returns null when the session
     * doesn't exist OR belongs to a different application. This is the
     * tenant-safe read for request handlers, where `sessionId` is
     * client-supplied: a leaked id from another agent must not resolve. The
     * filter is in SQL (`id = $1 AND application_id = $2`), so the scoping holds
     * even if a caller forgets to compare afterwards. Ingress handlers reach it
     * via `getOwnedSession(ctx, id)`; plain `get` stays for trusted internal
     * callers (runner claim loop, sweep) that legitimately fetch by id alone.
     */
    getForApplication(sessionId: string, applicationId: string): Promise<AgentSession | null>
    /**
     * Find an existing session matching `(application_id, external_key,
     * revision_id)`. `revisionId` is part of the lookup, not a filter applied
     * afterward, so resume never crosses a revision boundary: a request routed
     * to one revision can only resume a session created on that same revision.
     * This keeps draft-preview runs talking to the draft they targeted —
     * rather than silently resuming the live session under a shared
     * external_key — and keeps two draft revisions previewed against the same
     * external_key isolated, so their conversation histories don't bleed
     * together. The filter lives in SQL (not an after-the-fact JS guard) so the
     * `ORDER BY updated_at DESC LIMIT 1` can never return a row from a
     * different revision.
     */
    findByExternalKey(applicationId: string, externalKey: string, revisionId: string): Promise<AgentSession | null>
    /**
     * Find an existing session matching (application_id, idempotency_key).
     * Returns null if no row exists (including when the key was nulled by the
     * 30-day retention sweep). Semantically distinct from
     * `findByExternalKey`: a hit here means "this exact request was already
     * accepted" — the caller returns the existing session id without
     * appending or resuming. See `cron-trigger-scheduler.md` §6.
     */
    findByIdempotencyKey(applicationId: string, idempotencyKey: string): Promise<AgentSession | null>
    /**
     * Null out `idempotency_key` on sessions older than `cutoff`. The
     * platform-wide janitor sweep runs this on a 30-day retention to keep
     * the partial unique index compact — by that point any retry that
     * would have collided has long since happened. Returns the count of
     * rows updated. Plan `cron-trigger-scheduler.md` §6 "Retention."
     */
    clearStaleIdempotencyKeys(cutoff: Date): Promise<number>
    /**
     * List sessions for one application, newest first. `limit` defaults to 100
     * so a buggy caller can't accidentally page through every session in the
     * project; supply an explicit larger value if needed (capped at 500
     * server-side). Filters compose with AND semantics.
     */
    listByApplication(applicationId: string, opts?: ListSessionsOpts): Promise<AgentSession[]>
    /**
     * Count sessions matching the same filters as `listByApplication`. Used
     * by paginated callers (the janitor wraps `{ results, count }`). `limit`
     * and `offset` are ignored — the count is over the full filtered set.
     */
    countByApplication(applicationId: string, opts?: Omit<ListSessionsOpts, 'limit' | 'offset'>): Promise<number>
    /**
     * Like `listByApplication` but returns {@link SessionSummary} rows (no
     * conversation transcript) for the list view — `turns` + `search_text` read
     * off persisted columns instead of detoasting JSONB.
     */
    listSummariesByApplication(applicationId: string, opts?: ListSessionsOpts): Promise<SessionSummary[]>
    /**
     * Roll up summary stats for an agent — drives the agent-detail
     * overview tiles. `since` filters cost + sessions count to a
     * trailing window (e.g. 24h). `liveCount` is independent of
     * `since`. `lastActivityAt` is the most recent `updated_at`
     * across all states (null when the agent has no sessions).
     */
    aggregateForApplication(applicationId: string, since: string): Promise<AggregateStats>
    /**
     * Same shape as `aggregateForApplication`, scoped to every agent
     * owned by a team. Drives the fleet-stats tile on the agents list.
     */
    aggregateForTeam(teamId: number, since: string): Promise<AggregateStats>
    /**
     * All sessions for a team currently in a live state — queued,
     * running, waiting. Drives the live-sessions panel. Capped at
     * `limit` (default 100) so a single call can't accidentally page
     * every session.
     */
    listLiveForTeam(teamId: number, opts?: { limit?: number }): Promise<AgentSession[]>
    /**
     * Re-queue sessions stuck in 'running' beyond the TTL (their worker
     * probably crashed). The session's conversation is preserved; a sibling
     * worker picks it up via the normal claim path.
     *
     * Poison-pill semantics: increments `retry_count` on every reap. Sessions
     * whose retry_count would exceed `maxRetries` are marked `failed` instead
     * of re-queued — a genuinely broken job (e.g. consistently crashes the
     * worker) won't loop forever.
     *
     * Returns `{ requeued, poisoned }` so the janitor can report both.
     */
    reapStuckRunning(thresholdMs: number, maxRetries: number): Promise<{ requeued: number; poisoned: number }>
    /**
     * Idle `completed` sessions whose `updated_at` is older than the floor
     * threshold. The sweep consumes this list and applies per-agent TTL
     * before deciding to close — `floorMaxAgeMs` is the platform-wide
     * default, sessions with an opt-in `spec.resume.max_completed_age_ms`
     * may still be retained.
     */
    listIdleCompleted(floorMaxAgeMs: number, limit?: number): Promise<AgentSession[]>
    /**
     * Count sessions grouped by state across the whole fleet. Backs the
     * janitor's queue-depth Prometheus gauge — the singleton samples this once
     * per sweep so we get `queued` backlog + `running` in-flight + terminal
     * counts without every runner pod hammering the same aggregate. Returns a
     * record keyed by state; states with no rows are simply absent (the caller
     * zero-fills the gauge for known states).
     */
    countByState(): Promise<Partial<Record<AgentSession['state'], number>>>
}
