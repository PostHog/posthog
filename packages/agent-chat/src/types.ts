/**
 * Public types for `@posthog/agent-chat`.
 *
 * Mirrors a client-side subset of `@posthog/agent-shared` so consumers (the
 * console, future PostHog frontend dock, customer SDKs) get a stable surface
 * without dragging in the full server contract.
 *
 * v0 is fixture-driven; v0.2 wires these to real ingress responses.
 */

export interface AgentApplicationRef {
    id: string
    slug: string
    name: string
}

export interface SessionPrincipal {
    kind: 'human' | 'system'
    /** PostHog user id when `kind === 'human'`. */
    userId?: string
    displayName: string
}

export type AssistantTurnPart =
    | { kind: 'text'; text: string }
    | { kind: 'thinking'; text: string }
    | {
          kind: 'tool_call'
          /** Tool id as it appears in the spec, e.g. `@posthog/query` or `@posthog/ui/focus`. */
          toolId: string
          callId: string
          /** Server-fulfilled or client-fulfilled. */
          fulfillment: 'server' | 'client'
          args: Record<string, unknown>
          result?: { ok: true; body: unknown } | { ok: false; error: string }
      }

export interface UserTurn {
    kind: 'user'
    id: string
    timestamp: string
    text: string
}

export interface AssistantTurn {
    kind: 'assistant'
    id: string
    timestamp: string
    parts: AssistantTurnPart[]
    /** True while the model is mid-stream. */
    streaming?: boolean
}

export type Turn = UserTurn | AssistantTurn

export interface PendingApproval {
    callId: string
    toolId: string
    args: Record<string, unknown>
    requestedAt: string
}

export interface SessionUsage {
    inputTokens: number
    outputTokens: number
    costUsd: number
}

/**
 * Session lifecycle state.
 *
 * Live states (session is in flight): `streaming` · `awaiting_approval` ·
 * `awaiting_client_tool` · `idle` (paused between turns) ·
 * `disconnected` (transport blip, session preserved).
 *
 * Terminal states (session is over): `completed` · `failed` · `cancelled` ·
 * `error` (live failure that ended the session).
 *
 * v0.1+ may add `suspended` per [`long-running-sessions.md`](docs/agent-platform/plans/long-running-sessions.md).
 */
export type SessionState =
    | 'idle'
    | 'streaming'
    | 'awaiting_approval'
    | 'awaiting_client_tool'
    | 'disconnected'
    | 'error'
    | 'completed'
    | 'failed'
    | 'cancelled'

/** True if the session is still active (not in a terminal state). */
export const LIVE_SESSION_STATES: ReadonlyArray<SessionState> = [
    'streaming',
    'awaiting_approval',
    'awaiting_client_tool',
    'idle',
    'disconnected',
]

export interface ChatSession {
    id: string
    application: AgentApplicationRef
    principal: SessionPrincipal
    turns: Turn[]
    state: SessionState
    pendingApprovals: PendingApproval[]
    usage: SessionUsage
    error?: string
    /** ISO timestamp the session was opened. v0.2 will come from the runner. */
    started_at?: string
    /** ISO timestamp the session reached a terminal state (completed/failed/aborted/error). */
    ended_at?: string
    /**
     * What kicked the session off. Drives the playback shell — a chat
     * trigger renders like a Claude conversation; a slack trigger renders
     * like a Slack thread; a cron trigger renders as an autonomous run.
     */
    trigger?: SessionTrigger
}

export type SessionTrigger =
    | { kind: 'chat' }
    | {
          kind: 'slack'
          workspace: string
          channelId: string
          channelName: string
          /** Slack ts of the message that mentioned the bot (also serves as thread root). */
          threadTs: string
          /** Original message text that started the thread. */
          rootMessage: string
          /** Display name of the user who pinged the bot. */
          invokedBy: string
      }
    | { kind: 'cron'; schedule: string; timezone?: string; firedAt: string }
    | { kind: 'webhook'; path: string; source?: string }

/* ──────────────────────────────────────────────────────────────────────────
 * Client-fulfilled tool handler API
 *
 * The spec author declares `kind: "client"` tools in the agent spec. The
 * connecting client (this package, when embedded) declares which of those
 * it can handle via `client.handles[]`. Handlers below provide the
 * implementation that runs in the browser when the model invokes one.
 * ──────────────────────────────────────────────────────────────────────── */

export interface ClientToolHandler<Args = Record<string, unknown>, Result = Record<string, unknown>> {
    id: string
    handle: (args: Args) => Promise<Result> | Result
}

/* ──────────────────────────────────────────────────────────────────────────
 * Well-known client tools — `@posthog/ui/*`
 *
 * Schemas are intentionally narrow types here for typing convenience; the
 * authoritative shape lives in the runner's well-known registry (§8.5 in
 * the agent-console-website plan) and v0.3 syncs the two via codegen.
 * ──────────────────────────────────────────────────────────────────────── */

/**
 * `@posthog/ui/focus` — drives URL navigation in the host console.
 * The host maps each `kind` to a route + push it. After every
 * successful navigation the host also refetches its data so pages
 * already on the target URL pick up changes the agent just made.
 */
export type FocusArgs =
    | { kind: 'tab'; tab: 'overview' | 'configuration' | 'sessions' }
    | { kind: 'file'; path: string }
    | { kind: 'revision'; revisionId: string }
    | { kind: 'session'; sessionId: string }
    | { kind: 'spec_section'; section: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits' }

export type FocusResult = { focused: true; kind: FocusArgs['kind'] } | { focused: false; reason: string }

export type ToastArgs = {
    level: 'info' | 'success' | 'warning' | 'error'
    message: string
}

export type ToastResult = { shown: true }
