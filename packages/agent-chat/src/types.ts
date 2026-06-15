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
    /**
     * True while the message has been accepted client-side / queued on
     * the server but the agent hasn't yet started the turn that
     * consumes it. Cleared on the next `turn_started` event.
     */
    pending?: boolean
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
 * Live states (session is in flight): `streaming` · `awaiting_user_input` ·
 * `awaiting_client_tool` · `idle` (paused between turns) ·
 * `disconnected` (transport blip, session preserved).
 *
 * Terminal states (session is over): `completed` · `failed` · `cancelled` ·
 * `error` (live failure that ended the session).
 *
 * Note: `awaiting_user_input` parks the session for a steering message
 * (today's only producer is `@posthog/meta-ask-for-input`). Approval-gated
 * tool calls do NOT park — they return a synthetic queued result and the
 * session keeps running. The old `awaiting_approval` name predated that
 * design and was renamed to remove the confusion.
 *
 * v0.1+ may add `suspended` per [`long-running-sessions.md`](docs/agent-platform/plans/long-running-sessions.md).
 */
export type SessionState =
    | 'idle'
    | 'streaming'
    | 'awaiting_user_input'
    | 'awaiting_client_tool'
    | 'disconnected'
    | 'error'
    | 'completed'
    | 'failed'
    | 'cancelled'

/** True if the session is still active (not in a terminal state). */
export const LIVE_SESSION_STATES: ReadonlyArray<SessionState> = [
    'streaming',
    'awaiting_user_input',
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
    /**
     * Coarse trigger source — always present where the session row recorded a
     * trigger (`trigger_metadata.kind`). The rich `trigger` above carries
     * render detail where it can be reconstructed; this is the universal
     * discriminator the session list shows as a badge and filters on.
     */
    triggerKind?: SessionTriggerKind
}

/** The trigger types a session can originate from — the `kind` of `SessionTrigger`. */
export type SessionTriggerKind = 'chat' | 'slack' | 'cron' | 'webhook' | 'mcp'

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
    | {
          kind: 'cron'
          /** `name` from `spec.triggers[].config.name` — the per-job handle the author gave this cron. */
          cronName: string
          schedule: string
          timezone?: string
          firedAt: string
          /** True when fired via `POST /revisions/:id/cron/fire` rather than the scheduler. */
          manual?: boolean
      }
    | { kind: 'webhook'; path: string; source?: string }

/* ──────────────────────────────────────────────────────────────────────────
 * Client-fulfilled tool handler API
 *
 * The spec author declares `kind: "client"` tools in the agent spec. The
 * connecting client (this package, when embedded) declares which of those
 * it can handle via `client.handles[]`. Handlers below provide the
 * implementation that runs in the browser when the model invokes one.
 * ──────────────────────────────────────────────────────────────────────── */

/**
 * Two delivery shapes share `ClientToolHandler`:
 *
 *   - **Synchronous handler** (`handle`) — the 99% case. The runner calls
 *     `handle(args)` the moment a `client_tool_call` event lands, awaits
 *     the promise, and POSTs the result back over ingress. `focus` /
 *     `toast` / `get_context` all use this shape today.
 *
 *   - **Inline renderer** (`render`) — for tools whose "answer" is a
 *     small interactive UI. The runner does NOT auto-invoke; instead the
 *     chat transcript renders the supplied node next to the matching
 *     `tool_call` part. The renderer calls `resolve(result)` (or
 *     `reject(reason)`) when the user submits, and the host posts the
 *     result back through the same ingress path the sync flow uses.
 *
 * A given tool id registers exactly one shape — pick `handle` or
 * `render`, not both. Hosts mix both kinds freely in `handlers[]`.
 */
export interface ClientToolRenderCallbacks<Result = Record<string, unknown>> {
    /** Resolve the call with a successful result. Idempotent — subsequent calls are dropped. */
    resolve: (result: Result) => void
    /** Resolve the call with a failure reason. The host POSTs it back as `{ error }`. */
    reject: (reason: string) => void
    /** The session id the tool call belongs to — useful for the inline UI's API calls. */
    sessionId: string
    /** The runner-issued call id — uniquely identifies this invocation. */
    callId: string
}

export interface ClientToolSyncHandler<Args = Record<string, unknown>, Result = Record<string, unknown>> {
    id: string
    handle: (args: Args) => Promise<Result> | Result
}

export interface ClientToolRenderHandler<Args = Record<string, unknown>, Result = Record<string, unknown>> {
    id: string
    render: (args: Args, callbacks: ClientToolRenderCallbacks<Result>) => React.ReactNode
}

export type ClientToolHandler<Args = Record<string, unknown>, Result = Record<string, unknown>> =
    | ClientToolSyncHandler<Args, Result>
    | ClientToolRenderHandler<Args, Result>

export function isRenderHandler<A, R>(h: ClientToolHandler<A, R>): h is ClientToolRenderHandler<A, R> {
    return 'render' in h
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
/**
 * `slug` is required on every variant — focus targets are always
 * scoped to a specific agent and the host should not silently fall
 * back to "whichever agent the user happens to be looking at". The
 * agent should pass it explicitly. The dock context still carries
 * the current page's agent — agents that want to stay on the same
 * one can read it via `get_context` and pass it through.
 */
export type FocusArgs =
    // Tab values mirror the actual agent-detail segment set under
    // `app/agents/[slug]/`. The host's `urlForFocus` composes the
    // matching path-based route.
    | { kind: 'tab'; tab: 'overview' | 'configuration' | 'connections' | 'sessions' | 'memory'; slug: string }
    | { kind: 'file'; path: string; slug: string }
    | { kind: 'revision'; revisionId: string; slug: string }
    | { kind: 'session'; sessionId: string; slug: string }
    | {
          kind: 'spec_section'
          section: 'triggers' | 'tools' | 'skills' | 'secrets' | 'limits'
          slug: string
      }

export type FocusResult = { focused: true; kind: FocusArgs['kind'] } | { focused: false; reason: string }

export type ToastArgs = {
    level: 'info' | 'success' | 'warning' | 'error'
    message: string
}

export type ToastResult = { shown: true }
