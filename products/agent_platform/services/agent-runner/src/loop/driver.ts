/**
 * Session driver — runs one claimed session to a turn-boundary stopping point
 * by handing control to pi-agent-core's `runAgentLoop` and translating its
 * `AgentEvent` stream back into PostHog's bus / log / analytics sinks and the
 * persisted conversation.
 *
 * Replaces the hand-rolled turn loop (`run-turn.ts`) + tool dispatcher
 * (`dispatch-one.ts` / `tool-dispatch.ts`) + stream normalizer
 * (`pi-client.ts`). The loop now owns: streaming, tool-arg validation, tool
 * dispatch (via each `AgentTool.execute`), and the turn/tool event stream.
 * This file owns everything PostHog-specific around it:
 *
 *   - hooks: `getSteeringMessages` drains `pending_inputs`; `shouldStopAfterTurn`
 *     enforces shutdown + `spec.limits.max_turns`; `getApiKey` / `apiKey` and
 *     `reasoning` plumb the model knobs.
 *   - the event sink: appends every finalized message to `session.conversation`
 *     (in order — the loop emits the assistant `message_end` before its tool
 *     results), mirrors lifecycle events to the SSE bus + log sink, emits one
 *     `$ai_generation` per turn and one `$ai_span` per tool call, accumulates
 *     `usage_total`, and persists after each turn.
 *   - outcome derivation: meta control-flow (`terminate` + `details.control`),
 *     shutdown, the turn cap, and `stopReason` collapse into a `RunOutcome` the
 *     worker maps to a session state.
 *
 * Suspension: the worker's shutdown `AbortSignal` is wired into both the loop's
 * `signal` (cancels the in-flight provider call) and `shouldStopAfterTurn` (a
 * clean turn-boundary stop). Either way the turn either completes or is
 * discarded and re-run on resume — the same turn-boundary checkpointing the
 * old loop had.
 *
 * Approval-gated tools queue via their wrapped `AgentTool.execute` (see the
 * gate override below) and resume when a decided marker lands in
 * `pending_inputs` — handled in `getSteeringMessages`.
 */

import type { AgentContext, AgentEvent, AgentEventSink, AgentMessage, StreamFn } from '@earendil-works/pi-agent-core'
import { runAgentLoop } from '@earendil-works/pi-agent-core'
import type { AssistantMessage, Message } from '@earendil-works/pi-ai'
import { streamSimple } from '@earendil-works/pi-ai'
import { randomUUID } from 'node:crypto'

import {
    accumulateUsage,
    AgentRevision,
    AgentSession,
    AnalyticsSink,
    analyticsDistinctId,
    ApprovalStore,
    AssistantMessageRecord,
    BundleStore,
    buildSystemPrompt,
    buildAskerIdentity,
    ConversationMessage,
    CredentialBroker,
    createLogger,
    extractGatewayRequestId,
    FRAMEWORK_PROMPT_VERSION,
    GatewayCatalog,
    GatewayClient,
    gatewaySettledCost,
    generationSpanId,
    HttpFetcher,
    IdentityCredentialStore,
    IdentityLinkStateStore,
    IdentityStore,
    isDeltaEventKind,
    LogLevel,
    LogSink,
    MemoryStore,
    NoopAnalyticsSink,
    parseClientToolResultMarker,
    postSlackApprovalButtons,
    postSlackReply,
    Sandbox,
    SecretBroker,
    SessionEvent,
    SessionEventBus,
    SessionEventKind,
    SessionInputsStore,
    SLACK_BOT_TOKEN_KEY,
    SlackStatusReporter,
    slackTextFromContent,
    resolveToolRefApprovalLevel,
    TabularStore,
    ToolContext,
    toolSpanId,
    WebSearchProvider,
} from '@posthog/agent-shared'
import { nativeToolApprovalClass } from '@posthog/agent-tools'

import { approvalMarkerRequestId, ApprovalPolicy, dispatchApprovedResult, queueApprovalResult } from './approval'
import { AgentToolDeps, buildAgentTools, MetaControl, RealToolExecute, ToolResultDetails } from './build-agent-tools'
import { fallbackStreamFn, ResolvedModel } from './fallback-stream'
import { assertToolsGated, gateTool, QueueGated } from './gate-tool'
import { resolveMaxOutputTokens } from './max-output-tokens'
import type { McpOpenFailure, OpenedMcp } from './mcp-clients'
import {
    isProxyReadOnlyHelper,
    lookupMcpToolApproval,
    PREFIX_SEPARATOR,
    proxiedPrefixesFromCallTools,
    resolveApprovedExecutor,
} from './mcp-tool-lookup'
import { providerSafeName } from './provider-safe-names'

/** The model id that served the most recent assistant turn, if any. Seeds the
 *  fallback wrapper's sticky lead / cost-mode pin so it survives suspend→resume,
 *  not just consecutive in-process turns. */
function lastServedModelId(conversation: ConversationMessage[]): string | undefined {
    for (let i = conversation.length - 1; i >= 0; i--) {
        const message = conversation[i]
        if (message.role === 'assistant' && message.model) {
            return message.model
        }
    }
    return undefined
}

export interface RunSessionDeps {
    /**
     * Priority-ordered models the loop tries (primary first, fallbacks after).
     * Resolved once per session from `modelPolicyToList(rev.spec)`. On a
     * fallback-eligible provider failure the wrapper retries the next entry.
     */
    models: ResolvedModel[]
    /** Per-call API key (provider-specific). */
    apiKey?: string
    /**
     * Stream function for the loop. Defaults to pi-ai's `streamSimple` (which
     * routes through the registered provider — real providers in prod, the faux
     * provider in the e2e harness). Injectable for unit tests.
     */
    streamFn?: StreamFn
    bundle: BundleStore
    sandbox: Sandbox | null
    secrets: Record<string, string>
    broker?: SecretBroker
    /**
     * Per-session credential store populated by ingress at /run + /send.
     * Tool dispatch resolves `(session_id, target) → Credential` through
     * here to get the user's auth materials (e.g. PostHog OAuth bearer
     * under target `posthog_api`). Optional — when absent, tools that
     * try to resolve credentials get `null` and degrade.
     */
    credentialBroker?: CredentialBroker
    /** Aborting this signal mid-turn cancels the LLM call and stops the loop. */
    shutdownSignal?: AbortSignal
    /**
     * Fresh read of the session's persisted state, called once at start-of-run
     * to catch a `/cancel` that landed in the gap between `queue.claim()` and
     * our bus subscription (the bus event is fire-and-forget, so a cancel
     * published before we subscribed is lost — but ingress also writes the
     * durable `cancelled` state). Wired from `queue.get` in the worker; absent
     * in unit tests that don't exercise the race.
     */
    getSessionState?: (sessionId: string) => Promise<AgentSession['state'] | null>
    /** Called once per turn after the assistant message + tool results are appended. */
    onTurnPersist?: (session: AgentSession) => Promise<void>
    /**
     * Atomic read+clear + append path for `pending_inputs`. The loop drains
     * via this at the start of each turn instead of operating on the
     * (potentially stale) `session.pending_inputs` it was claimed with, so
     * a `/send` that lands mid-turn either gets included in this turn (if
     * it commits before the drain) or queues cleanly for the next (if it
     * commits after). `PgSessionQueue` satisfies the interface — wire the
     * queue here directly.
     */
    inputs: SessionInputsStore
    bus: SessionEventBus
    logs: LogSink
    analytics?: AnalyticsSink
    /** Agent display name, used to name the `$ai_trace`. Falls back to the slug, then the app id. */
    applicationName?: string
    /**
     * True on the ai-gateway path: the gateway emits its own `$ai_generation`
     * (settled cost + the `X-PostHog-Properties` attribution), so the runner
     * suppresses its duplicate. Still emits `$ai_span`/`$ai_trace` and still
     * settles cost into the session row via `gatewayUsage`.
     */
    gatewayEmitsGenerations?: boolean
    /** Approval-gated tool store. MANDATORY — gated tools queue instead of
     * executing and resume via the decided-marker path in getSteeringMessages.
     * `runSession` throws if it's missing rather than running gated tools
     * ungated (a `requires_approval` flag that silently does nothing is a
     * security hole). No mock variant. */
    approvals: ApprovalStore
    buildApprovalUrl?: (requestId: string) => string
    /**
     * S3-backed memory store. Threaded into `AgentToolDeps` → `ToolContext`
     * so native `@posthog/memory-*` tools work; absent → memory tools return
     * `memory_store_unavailable` to the model. Wired in prod from
     * `AGENT_MEMORY_S3_*` config.
     */
    memoryStore?: MemoryStore
    /** Deterministic tabular store for @posthog/table-* tools. */
    tabularStore?: TabularStore
    /** Web-search provider chain for @posthog/web-search; empty → tool gated out. */
    webSearchProviders?: readonly WebSearchProvider[]
    /**
     * Per-session static HTTP headers stamped on every outbound model call.
     * On the ai-gateway path this carries `X-PostHog-Distinct-Id`,
     * `X-PostHog-Trace-Id`, and `X-PostHog-Properties` (the `$agent_*`
     * attribution) so the gateway-emitted `$ai_generation` events attribute to
     * the right user, trace, and agent application. The `gatewayMetadataStreamFn`
     * wrapper merges these with a per-turn `Idempotency-Key` of the form
     * `agent:<session>:<turn>:<nonce>` and forwards them to pi-ai's per-call
     * `options.headers` (it does NOT send `X-Request-Id` — the gateway mints its
     * own and returns it in the response header). Presence also signals
     * `errorContext()` to mark failures as `source: ai_gateway`.
     */
    gatewayHeaders?: Record<string, string>
    /**
     * Gateway read client + the team's `phc_` bearer. When set, after every
     * pi-ai turn the runner fetches `GET /v1/usage/<request_id>` (using the
     * gateway's settlement id captured from the response by
     * `gatewayMetadataStreamFn`) and merges the gateway-computed cost into
     * `usage_total.cost_total`. Best-effort: a transient fetch failure, a
     * missing id, or a NaN body is logged/skipped so a gateway blip can't
     * strand the turn.
     */
    gatewayUsage?: {
        client: GatewayClient
        phc: string
    }
    /**
     * Opened MCP clients (one per entry in `rev.spec.mcps[]`). Forwarded
     * straight into `AgentToolDeps`; `buildAgentTools` walks them at session
     * start to emit one `AgentTool` per remote tool. Lifetime is owned by
     * the worker (`openMcpClients` before `runSession`, `close` in the
     * worker's `finally`). Absent or empty → no MCP tools surface.
     */
    mcpClients?: OpenedMcp[]
    /**
     * Per-ref failures from `openMcpClients` for the MCPs that did NOT open
     * successfully. Threaded into the system prompt so the model is told
     * which capabilities are unavailable for this session and can shape
     * its response accordingly. The full `devReason` of each entry is
     * intentionally NOT included in the model-visible text — it lives in
     * `log_entries` for the agent owner. Absent / empty → all MCPs opened.
     */
    mcpFailures?: McpOpenFailure[]
    /**
     * Outbound HTTP client for native tools — threaded through to
     * `AgentToolDeps` and then `ToolContext.http`. Required so tools can
     * assume the seam is present; wired once at the runner entrypoint
     * from `HTTPS_PROXY` env (smokescreen in prod, direct in dev).
     */
    http: HttpFetcher
    /** Base URL for the PostHog API. Forwarded into `ToolContext.posthogApiBaseUrl`. */
    posthogApiBaseUrl: string
    /** Gateway model catalog; forwarded into `ToolContext.gatewayCatalog`. */
    gatewayCatalog?: GatewayCatalog
    /** Operator override (AGENT_MAX_OUTPUT_TOKENS); clamps below model.maxTokens. */
    maxOutputTokensOverride?: number
    /**
     * Per-asker identity linking (spec.identity_providers). When both stores are
     * wired and the spec declares providers, `ctx.identity` resolves the run's
     * asker's linked credential (or a link). Omit to disable identity tools.
     */
    identityCredentials?: IdentityCredentialStore
    identityLinks?: IdentityLinkStateStore
    /** Resolves a non-slack principal to its AgentUser id for linking. */
    identities?: IdentityStore
    /** OAuth callback base; `/link/<provider>/callback` is appended. */
    linkRedirectBaseUrl?: string
}

export type RunOutcome =
    | { state: 'completed'; turns: number }
    | { state: 'closed'; summary?: string; turns: number }
    | { state: 'suspended'; reason: 'shutdown'; turns: number }
    | { state: 'failed'; reason: string; turns: number }

export async function runSession(rev: AgentRevision, session: AgentSession, deps: RunSessionDeps): Promise<RunOutcome> {
    // Fail-closed: never run a session with approval gating disabled. `Worker`
    // already guards at construction; this catches any direct `runSession`
    // caller (tests, future entrypoints) so a `requires_approval` tool can
    // never silently dispatch ungated.
    if (!deps.approvals) {
        throw new Error('RunSessionDeps.approvals is required — refusing to run with approval gating disabled.')
    }
    if (deps.models.length === 0) {
        throw new Error('RunSessionDeps.models is required — resolve via modelPolicyToList(rev.spec).')
    }
    // Primary (highest-priority) model — identity for max-tokens, error context,
    // and the analytics fallback tag. Fallbacks (if any) live after it.
    const primaryModel = deps.models[0].model
    // Slack-triggered sessions: the runner relays each finalized assistant
    // message into the thread (see the turn_end handler). The model is told as
    // much so it replies in natural language instead of forcing everything
    // through the slack-post-message tool.
    //
    // Slack-triggered sessions relay the model's reply back into the originating
    // thread (the system prompt below tells the model to answer in natural
    // language instead of calling a slack tool).
    const slackReply = session.trigger_metadata?.kind === 'slack' ? session.trigger_metadata : null
    const system = await buildSystemPrompt(rev, deps.bundle, {
        unavailableMcps: (deps.mcpFailures ?? []).map((f) => ({
            id: f.ref.id,
            category: f.category,
            authorizeUrl: f.authorizeUrl,
        })),
        slackReplyRelay: slackReply !== null,
    })
    const bus: SessionEventBus = deps.bus
    const logs: LogSink = deps.logs
    const analytics: AnalyticsSink = deps.analytics ?? new NoopAnalyticsSink()
    const distinctId = analyticsDistinctId(session)

    const runLog = createLogger('runner', {
        session_id: session.id,
        application_id: session.application_id,
        team_id: session.team_id,
    })
    const log = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void => {
        runLog[level](meta ?? {}, msg)
    }

    // Slack "working on it" status: a message the runner keeps in the thread
    // while a turn is in flight and removes when a real reply lands. Null for
    // non-slack sessions.
    const slackStatus = slackReply
        ? new SlackStatusReporter({
              http: deps.http,
              token: deps.secrets[SLACK_BOT_TOKEN_KEY],
              channel: slackReply.channel,
              thread_ts: slackReply.thread_ts,
              sessionId: session.id,
              logger: { warn: (meta, m) => log('warn', m, meta), info: (meta, m) => log('info', m, meta) },
          })
        : null

    const emit = async (kind: SessionEventKind, data: Record<string, unknown> = {}): Promise<void> => {
        const ts = new Date().toISOString()
        await bus.publish({ session_id: session.id, kind, data, ts } satisfies SessionEvent)
        // Drop high-cardinality delta events from the persistent log sink; the
        // turn-end full-text events still land.
        if (isDeltaEventKind(kind)) {
            return
        }
        const level: LogLevel = kind === 'failed' ? 'error' : 'info'
        await logs.write([
            {
                ts,
                team_id: session.team_id,
                application_id: session.application_id,
                session_id: session.id,
                level,
                event: kind,
                data,
            },
        ])
    }

    /**
     * `failed` is the one event whose payload leaks implementation detail
     * — raw provider error strings, model + provider ids, internal URLs
     * from MCP transports, etc. Any of that on the SSE bus means any chat
     * client (not just the agent owner) sees it. We split: publish a
     * deliberately empty payload to the bus (state=failed is enough for
     * the chat UI to render a generic banner), and stash the full reason
     * + context in log_entries so the agent owner can debug via the
     * session-detail page. Keep both this and the worker's pre_run_session
     * failure path in sync.
     */
    const emitFailure = async (reason: string, logExtras: Record<string, unknown> = {}): Promise<void> => {
        const ts = new Date().toISOString()
        await bus.publish({ session_id: session.id, kind: 'failed', data: {}, ts } satisfies SessionEvent)
        await logs.write([
            {
                ts,
                team_id: session.team_id,
                application_id: session.application_id,
                session_id: session.id,
                level: 'error',
                event: 'failed',
                data: { reason, ...logExtras },
            },
        ])
    }

    // Dispatcher for `kind: "client"` tools. Subscribes once for the session
    // and routes every `client_tool_result` event to whichever pending
    // promise has the matching call_id. The subscription is torn down +
    // pending promises rejected at session-end via the wrapping
    // try/finally below — otherwise the bus would accumulate one
    // subscriber per session handled by this worker.
    const pendingClientCalls = new Map<string, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()
    // Per-session stop signal. Fired by a `cancel` bus event (user hit the chat
    // stop button) — aborts the in-flight provider call and reopens the session
    // as `completed` rather than re-queuing it. Merged with `shutdownSignal`
    // before it reaches the loop; the two are kept distinct so their outcomes
    // can diverge (cancel → completed/open, shutdown → suspended/requeued).
    const cancelController = new AbortController()
    const clientResultUnsub = bus.subscribe(session.id, (e) => {
        if (e.kind === 'cancel') {
            if (!cancelController.signal.aborted) {
                runLog.info({}, 'session.cancel.received')
                cancelController.abort()
            }
            return
        }
        if (e.kind !== 'client_tool_result') {
            return
        }
        const d = e.data as { call_id?: string; result?: unknown; error?: string }
        if (!d.call_id) {
            return
        }
        const pending = pendingClientCalls.get(d.call_id)
        if (!pending) {
            return
        }
        pendingClientCalls.delete(d.call_id)
        // Key presence — not truthiness. An empty-string `error` still
        // means the handler failed; falling through to resolve(undefined)
        // would let pi-ai see malformed tool content and emit a silent
        // `ok: false, error: ""` to the model.
        if ('error' in d) {
            pending.reject(new Error(d.error || 'empty_client_error'))
        } else {
            pending.resolve(d.result)
        }
    })
    const tearDownClientDispatch = (): void => {
        clientResultUnsub()
        for (const p of pendingClientCalls.values()) {
            p.reject(new Error('session_ended'))
        }
        pendingClientCalls.clear()
    }
    const dispatchClientTool = async (
        toolId: string,
        args: Record<string, unknown>,
        timeoutMs: number
    ): Promise<unknown> => {
        const callId = randomUUID()
        const promise = new Promise<unknown>((resolve, reject) => {
            pendingClientCalls.set(callId, { resolve, reject })
            setTimeout(() => {
                if (pendingClientCalls.delete(callId)) {
                    reject(new Error('client_tool_timeout'))
                }
            }, timeoutMs)
        })
        await emit('client_tool_call', { call_id: callId, tool_id: toolId, args })
        return promise
    }

    // Wrap the loop + outcome derivation in try/finally so the bus
    // subscription registered above is always released (and pending
    // client-tool promises rejected) regardless of which return path
    // the function exits through. Intentionally left at +0 indent to
    // keep the diff small; the contents are unchanged.
    try {
        // Identity resolution keys off the session OWNER (the authenticated
        // principal), not whoever spoke last — a credential is never resolved
        // for the wrong person. In a shared participant thread (any trusted user
        // can post) owner != asker, so identity-gated tools fail closed there
        // rather than act as the owner on a participant's behalf (T1).
        let identity: ToolContext['identity']
        if (deps.identityCredentials && deps.identityLinks) {
            identity = await buildAskerIdentity(rev, session, {
                credentials: deps.identityCredentials,
                links: deps.identityLinks,
                identities: deps.identities,
                credentialBroker: deps.credentialBroker,
                http: deps.http,
                secret: (name) => deps.secrets[name],
                posthogApiBaseUrl: deps.posthogApiBaseUrl,
                linkRedirectBaseUrl: deps.linkRedirectBaseUrl,
                log,
            })
        }
        const toolDeps: AgentToolDeps = {
            rev,
            session,
            sandbox: deps.sandbox,
            secrets: deps.secrets,
            bundle: deps.bundle,
            log,
            memoryStore: deps.memoryStore,
            tabularStore: deps.tabularStore,
            webSearchProviders: deps.webSearchProviders,
            dispatchClientTool,
            emitClientToolCall: async (callId, toolId, args) => {
                await emit('client_tool_call', { call_id: callId, tool_id: toolId, args })
            },
            credentialBroker: deps.credentialBroker,
            identity,
            mcpClients: deps.mcpClients,
            http: deps.http,
            posthogApiBaseUrl: deps.posthogApiBaseUrl,
            gatewayCatalog: deps.gatewayCatalog,
        }
        const { tools, nameToId, mcpProxyCallTools } = await buildAgentTools(rev, toolDeps)

        await emit('session_started', {
            team_id: session.team_id,
            agent: rev.application_id,
            rev: rev.id,
            framework_prompt_version: FRAMEWORK_PROMPT_VERSION,
        })

        // Clean suspension point before any work — matches the old top-of-loop check.
        if (deps.shutdownSignal?.aborted) {
            return { state: 'suspended', reason: 'shutdown', turns: 0 }
        }

        // Stop signal that landed before we subscribed (the publish→subscribe
        // race, or a session marked `cancelled` while still queued): the bus
        // event is gone, but ingress also wrote the durable `cancelled` state.
        // Reopen as `completed` so the conversation stays live — nothing ran,
        // so there is no partial output or usage to account for.
        if (cancelController.signal.aborted || (await deps.getSessionState?.(session.id)) === 'cancelled') {
            await emit('interrupted', { turns: 0 })
            return { state: 'completed', turns: 0 }
        }

        // Per-run state the sink accumulates; outcome derivation reads it after the loop.
        let turn = 0
        // Text streamed during the current turn, accumulated from `text_delta`
        // so a mid-stream cancel can persist the partial assistant reply. Reset
        // at `turn_start`; cleared at assistant `message_end` (the full message
        // is already in the conversation, so there is nothing partial to keep).
        let partialAssistantText = ''
        let inputSnapshot: ConversationMessage[] = []
        let turnStart = 0
        let genSpan = ''
        let stoppedByCap = false
        let lastStopReason: AssistantMessage['stopReason'] | undefined
        let lastError: string | undefined
        let lastControl: MetaControl | undefined
        let controlThisTurn: MetaControl | undefined
        let lastTurnContinued = false
        // Trace-level summary state — the input that opened the session and the
        // last assistant output, used to name + populate the `$ai_trace` event.
        const traceInput: ConversationMessage[] = [...session.conversation]
        let lastOutput: unknown = null
        const toolStarts = new Map<string, { args: Record<string, unknown>; t0: number }>()

        // Keep each tool's real execute (what an approved call runs on resume,
        // once the human has cleared the gate), then rebuild every tool through
        // `gateTool`. `approvals` is mandatory (runSession throws otherwise), so
        // gating is unconditional — there is no ungated fast path.
        const realExecute = new Map<string, RealToolExecute>()
        for (const tool of tools) {
            // Tools are named with their original id.
            realExecute.set(tool.name, tool.execute as RealToolExecute)
        }
        {
            const approvals = deps.approvals
            // Shared by every lane's resolver below. Every gated call queues for
            // a human decision — being the asker is not consent to the specific
            // call (the model could have been steered by content it read).
            // `toolName` is what the approval row records.
            const queueGated: QueueGated = async (toolName, toolCallId, args, policy) => {
                const queued = await queueApprovalResult({
                    approvals,
                    buildApprovalUrl: deps.buildApprovalUrl,
                    session,
                    revisionId: rev.id,
                    turn,
                    toolName,
                    toolCallId,
                    args,
                    policy,
                })
                // `principal` + Slack: post Approve/Reject buttons in-thread
                // (best-effort; skip a deduped re-queue).
                const reqId = queued.details?.requestId
                if (slackReply && policy.type === 'principal' && reqId && !queued.details?.deduped) {
                    void postSlackApprovalButtons(deps.http, {
                        token: deps.secrets[SLACK_BOT_TOKEN_KEY],
                        channel: slackReply.channel,
                        thread_ts: slackReply.thread_ts,
                        sessionId: session.id,
                        requestId: reqId,
                        toolName,
                        logger: {
                            warn: (meta, msg) => log('warn', msg, meta),
                            info: (meta, msg) => log('info', msg, meta),
                        },
                    }).catch(() => {})
                }
                return queued
            }

            // Prefixes whose connection is proxied (`<prefix>__call_tool` exists),
            // so the synthetic read-only helpers below can be recognised as ours.
            const proxiedPrefixes = proxiedPrefixesFromCallTools(mcpProxyCallTools.keys())

            for (let i = 0; i < tools.length; i++) {
                const tool = tools[i]
                const id = tool.name
                // Proxy `call_tool` gates dynamically: the underlying tool is
                // only known at call time (the `tool_name` arg), so re-key the
                // gate on `<prefix>__<tool_name>` per call.
                const proxyEntry = mcpProxyCallTools.get(id)
                if (proxyEntry) {
                    tools[i] = gateTool(
                        tool,
                        (_toolCallId, args) => {
                            const raw = typeof args.tool_name === 'string' ? args.tool_name : ''
                            // Resolve the same way `call_tool` will at dispatch time
                            // (mcp-proxy.ts `resolveProxyRemoteName`): prefer the raw
                            // name when it exists in the exposed catalog, only strip
                            // `<prefix>__` when the stripped name does. Gate and dispatch
                            // must key on the same name or one tool gates while another runs.
                            const remoteName = proxyEntry.resolveRemoteName(raw)
                            const exposedName = `${proxyEntry.client.prefix}${PREFIX_SEPARATOR}${remoteName}`
                            const gate = lookupMcpToolApproval(exposedName, rev.spec)
                            return gate?.requires_approval
                                ? { gate: true, toolName: exposedName, policy: gate.approval_policy }
                                : { gate: false }
                        },
                        queueGated
                    )
                    continue
                }
                // Synthetic proxy read-only helpers (`explore_tools` /
                // `get_tool_schema`) for a PROXIED connection are ungated catalog/
                // schema browsing — gating them would block enumeration on a human
                // and defeat the proxy. The blanket exemption was removed from
                // `lookupMcpToolApproval` (which can't tell a synthetic helper from
                // a real same-named tool); the proxy-aware check lives here.
                if (isProxyReadOnlyHelper(id, proxiedPrefixes)) {
                    tools[i] = gateTool(tool, () => ({ gate: false }), queueGated)
                    continue
                }

                // Native + custom tools carry their approval policy on
                // `spec.tools[]`. MCP tools materialise at session start
                // from `client.listTools()` so they can't appear there;
                // fall through to the lookup that decomposes the
                // `<prefix>__<remoteName>` shape against `spec.mcps[]`.
                // Client tools have no approval field today so they skip
                // either path. (PR 7 — runtime-mcps.md "Resolved design".)
                const ref = rev.spec.tools.find((t) => t.id === id)
                // The effective approval level FLOORS the spec's `requires_approval`:
                // a mutating native tool (intrinsic class `approve`, e.g.
                // `@posthog/memory-write`) is gated even when the author left
                // `requires_approval` false. Authors may tighten (set
                // `requires_approval`), never loosen below intrinsic.
                const nativeRef =
                    ref &&
                    ref.kind !== 'client' &&
                    resolveToolRefApprovalLevel(ref, { nativeApprovalClass: nativeToolApprovalClass }) === 'approve'
                        ? ref
                        : null
                // Only fall through to MCP lookup when there's NO `spec.tools`
                // entry at all. A `client` tool whose id collides with an
                // MCP-exposed `<prefix>__<remote>` name is an author bug —
                // refuse to gate it with the MCP's policy rather than
                // surprising the client-tool dispatcher. The dispatch
                // collision-skip in `build-agent-tools.ts` handles the
                // surface side; this just keeps the wrap path consistent.
                const mcpGate = ref ? null : lookupMcpToolApproval(id, rev.spec)
                const policy: ApprovalPolicy | null = nativeRef
                    ? (nativeRef.approval_policy as ApprovalPolicy)
                    : mcpGate?.requires_approval
                      ? mcpGate.approval_policy
                      : null
                tools[i] = gateTool(
                    tool,
                    () => (policy ? { gate: true, toolName: id, policy } : { gate: false }),
                    queueGated
                )
            }
        }

        // Fail-closed: every tool must be `gateTool`-branded before dispatch
        // (see gate-tool.ts).
        assertToolsGated(tools)

        const sink: AgentEventSink = async (event: AgentEvent): Promise<void> => {
            switch (event.type) {
                case 'turn_start': {
                    turn++
                    controlThisTurn = undefined
                    partialAssistantText = ''
                    // Reset fallback tracking; the wrapper's hooks repopulate it
                    // for this turn's outbound call(s).
                    modelAttempt = 0
                    fellBackFrom = undefined
                    await emit('turn_started', { turn })
                    // Show "working on it" in the thread while this turn runs.
                    await slackStatus?.start(':hourglass_flowing_sand: _Working on it…_')
                    return
                }
                case 'message_start': {
                    // Snapshot the model input + start the generation span when the
                    // assistant turn begins (steering messages for this turn are
                    // already appended via their own message_end).
                    if (event.message.role === 'assistant') {
                        inputSnapshot = [...session.conversation]
                        turnStart = Date.now()
                        genSpan = generationSpanId(session.id, turn)
                    }
                    return
                }
                case 'message_update': {
                    const e = event.assistantMessageEvent
                    if (e.type === 'text_delta') {
                        partialAssistantText += e.delta
                        await emit('assistant_text_delta', { turn, text: e.delta })
                    } else if (e.type === 'thinking_delta') {
                        await emit('assistant_thinking_delta', { turn, thinking: e.delta })
                    }
                    return
                }
                case 'message_end': {
                    // Every finalized message (steering/user, assistant, tool result)
                    // lands in the persisted transcript in emission order.
                    session.conversation.push(event.message as ConversationMessage)
                    // The assistant turn finalized normally — drop the partial
                    // buffer so a cancel between turns doesn't re-persist it.
                    if (event.message.role === 'assistant') {
                        partialAssistantText = ''
                    }
                    return
                }
                case 'tool_execution_start': {
                    toolStarts.set(event.toolCallId, {
                        args: (event.args ?? {}) as Record<string, unknown>,
                        t0: Date.now(),
                    })
                    await emit('tool_call', { name: event.toolName, args: event.args, id: event.toolCallId })
                    // Reflect the in-flight tool in the "working" status.
                    await slackStatus?.update(
                        `:hourglass_flowing_sand: _Working on it… (\`${event.toolName.replace(/^@posthog\//, '')}\`)_`
                    )
                    return
                }
                case 'tool_execution_end': {
                    const original = event.toolName
                    const started = toolStarts.get(event.toolCallId)
                    const details = event.result?.details as ToolResultDetails | undefined
                    if (details?.control) {
                        lastControl = details.control
                        controlThisTurn = details.control
                    }
                    const errorText = event.isError ? resultText(event.result) : undefined
                    await emit('tool_result', {
                        name: original,
                        id: event.toolCallId,
                        ok: !event.isError,
                        error: errorText,
                        // Surface the structured output so the live SSE
                        // reducer can render the same result the persisted
                        // session conversation shows on reload. Without
                        // this the client sees only `ok`/`error`.
                        output: event.isError ? undefined : (details?.output ?? null),
                        // Mirror the persisted synthetic envelope so a live viewer
                        // and a reload-from-transcript viewer build the same card
                        // (request id, edit affordance, principal-vs-agent scope).
                        ...(details?.queued
                            ? {
                                  approval: {
                                      request_id: details.requestId,
                                      state: 'queued',
                                      allow_edit: details.allowEdit,
                                      approver_scope: { type: details.approverType },
                                  },
                              }
                            : {}),
                    })
                    // A queued gated call didn't really execute — no span for it
                    // (the approved dispatch emits its own span on resume).
                    if (!details?.queued) {
                        await analytics.write([
                            {
                                kind: 'span',
                                ts: new Date().toISOString(),
                                team_id: session.team_id,
                                application_id: session.application_id,
                                revision_id: rev.id,
                                session_id: session.id,
                                turn,
                                span_id: toolSpanId(session.id, turn, event.toolCallId),
                                parent_span_id: genSpan,
                                distinct_id: distinctId,
                                tool_name: original,
                                tool_call_id: event.toolCallId,
                                input: started?.args ?? {},
                                output: event.isError ? null : (details?.output ?? null),
                                latency_ms: started ? Date.now() - started.t0 : 0,
                                is_error: event.isError,
                                error: errorText,
                            },
                        ])
                    }
                    return
                }
                case 'turn_end': {
                    const msg = event.message as AssistantMessage
                    lastStopReason = msg.stopReason
                    lastError = msg.errorMessage
                    lastOutput = msg.content
                    const hasToolCalls = msg.content.some((b) => b.type === 'toolCall')
                    lastTurnContinued = hasToolCalls && !controlThisTurn

                    const record: AssistantMessageRecord = {
                        role: 'assistant',
                        content: msg.content,
                        api: msg.api,
                        provider: msg.provider,
                        model: msg.model,
                        usage: msg.usage,
                        stopReason: msg.stopReason,
                        errorMessage: msg.errorMessage,
                        timestamp: msg.timestamp,
                    }
                    session.usage_total = accumulateUsage(session.usage_total, record)

                    for (const b of msg.content) {
                        if (b.type === 'text' && b.text) {
                            await emit('assistant_text', { text: b.text })
                        }
                    }

                    // Slack relay: post this finalized assistant message into the
                    // originating thread. The model just replies normally; the
                    // platform owns Slack delivery (mirrors how chat streams text
                    // to the console). Never throws — a Slack hiccup must not break
                    // the loop. Turns with no prose (pure tool calls) post nothing.
                    if (slackReply) {
                        const replyText = slackTextFromContent(msg.content)
                        if (replyText) {
                            const posted = await postSlackReply(deps.http, {
                                token: deps.secrets[SLACK_BOT_TOKEN_KEY],
                                channel: slackReply.channel,
                                thread_ts: slackReply.thread_ts,
                                text: replyText,
                                sessionId: session.id,
                                logger: {
                                    warn: (meta, m) => log('warn', m, meta),
                                    info: (meta, m) => log('info', m, meta),
                                },
                            })
                            // Only drop the "working" status once the reply is
                            // visibly in the thread — otherwise a failed post
                            // would leave the thread with neither status nor
                            // reply. A subsequent turn re-posts the status.
                            if (posted) {
                                await slackStatus?.clear()
                            }
                        }
                    }

                    // Gateway settled-cost recovery: `accumulateUsage` never
                    // trusts pi-ai estimates, so `GET /v1/usage/<request_id>` is
                    // the sole source of the session row's cost on this path.
                    // Best-effort — a failed/NaN fetch leaves cost_total
                    // unchanged (the gateway's own $ai_generation still carries
                    // the cost).
                    if (deps.gatewayUsage) {
                        const requestId = turnRequestIds.get(turn)
                        if (requestId) {
                            try {
                                const usage = await deps.gatewayUsage.client.getUsage(requestId, {
                                    phc: deps.gatewayUsage.phc,
                                })
                                if (usage) {
                                    const settled = gatewaySettledCost(usage)
                                    if (settled) {
                                        session.usage_total = {
                                            ...session.usage_total,
                                            cost_total: session.usage_total.cost_total + settled.usd,
                                        }
                                    } else {
                                        runLog.warn(
                                            { turn, cost_usd: usage.cost_usd, requestId },
                                            'gateway.usage.cost_nan'
                                        )
                                    }
                                }
                            } catch (err) {
                                runLog.warn(
                                    { turn, requestId, err: (err as Error).message },
                                    'gateway.usage.fetch_failed'
                                )
                            }
                        }
                        // Always clear the entry so the map can't accumulate across a
                        // long-running session — we don't need it after this turn.
                        turnRequestIds.delete(turn)
                    }

                    // Gateway path: the gateway emits the `$ai_generation` (with
                    // cost), so skip ours to avoid double-counting. Direct path:
                    // emit without cost and let ingestion price it — pi-ai's
                    // estimate is never used.
                    if (!deps.gatewayEmitsGenerations) {
                        await analytics.write([
                            {
                                kind: 'generation',
                                ts: new Date(msg.timestamp).toISOString(),
                                team_id: session.team_id,
                                application_id: session.application_id,
                                revision_id: rev.id,
                                session_id: session.id,
                                turn,
                                span_id: genSpan,
                                distinct_id: distinctId,
                                // The model that ACTUALLY answered: pi-ai stamps the
                                // answering model on `msg`, so a fallback turn tags the
                                // fallback model. Falls back to the resolved primary id.
                                model: msg.model ?? deps.models[modelAttempt]?.model.id ?? primaryModel.id,
                                provider:
                                    msg.provider ?? deps.models[modelAttempt]?.model.provider ?? primaryModel.provider,
                                // Marker when this turn fell over to a non-primary model.
                                model_attempt: modelAttempt > 0 ? modelAttempt : undefined,
                                fallback_from: fellBackFrom,
                                input: inputSnapshot,
                                output: msg.content,
                                input_tokens: msg.usage?.input ?? 0,
                                output_tokens: msg.usage?.output ?? 0,
                                cache_read_tokens: msg.usage?.cacheRead,
                                cache_write_tokens: msg.usage?.cacheWrite,
                                total_tokens: msg.usage?.totalTokens,
                                latency_ms: Date.now() - turnStart,
                                stop_reason: msg.stopReason,
                                is_error: msg.stopReason === 'error',
                                error: msg.stopReason === 'error' ? msg.errorMessage : undefined,
                            },
                        ])
                    }
                    await deps.onTurnPersist?.(session)
                    return
                }
                default:
                    return
            }
        }

        const context: AgentContext = {
            systemPrompt: system,
            messages: [...session.conversation] as unknown as AgentMessage[],
            tools,
        }

        // Per-turn gateway metadata: an `agent:<session>:<turn>` request id stamped
        // on every outbound call, exposed back into the sink via this map so
        // `turn_end` can read the settled cost (cleared per turn after the fetch
        // so the map can't grow unbounded). Populated on the gateway path only.
        const turnRequestIds = new Map<number, string>()

        // Cleanup for a cancel that interrupted an in-flight turn: persist the
        // partial reply and recover its usage, then reopen the session as
        // `completed`. The guards make it a no-op when the turn actually
        // finalized (cancel caught *between* turns) — `turn_end` already
        // persisted the message, cleared `partialAssistantText`, and deleted
        // the request id, so there's nothing left to do but emit the event.
        const finishInterrupted = async (): Promise<RunOutcome> => {
            if (partialAssistantText.trim().length > 0) {
                session.conversation.push({
                    role: 'assistant',
                    content: [{ type: 'text', text: partialAssistantText }],
                    model: primaryModel.id,
                    provider: primaryModel.provider,
                    stopReason: 'aborted',
                    timestamp: Date.now(),
                } satisfies AssistantMessageRecord)
                partialAssistantText = ''
            }
            // Mid-stream abort skips `turn_end`, so recover the interrupted
            // turn's tokens/cost here. The gateway settles usage for a
            // client-aborted request keyed on our `X-Request-Id`, and
            // `getUsage` already retries the small settle window. Best-effort:
            // billing is also captured gateway-side via its own
            // `$ai_generation`, so a miss only dents the session row's total.
            if (deps.gatewayUsage && turn > 0) {
                const requestId = turnRequestIds.get(turn)
                if (requestId) {
                    try {
                        const usage = await deps.gatewayUsage.client.getUsage(requestId, {
                            phc: deps.gatewayUsage.phc,
                        })
                        if (usage) {
                            const settled = gatewaySettledCost(usage)
                            session.usage_total = {
                                ...session.usage_total,
                                tokens_in: session.usage_total.tokens_in + (usage.input_tokens ?? 0),
                                tokens_out: session.usage_total.tokens_out + (usage.output_tokens ?? 0),
                                cost_total: session.usage_total.cost_total + (settled?.usd ?? 0),
                            }
                        }
                    } catch (err) {
                        runLog.warn({ turn, requestId, err: (err as Error).message }, 'cancel.usage.fetch_failed')
                    }
                    turnRequestIds.delete(turn)
                }
            }
            await emit('interrupted', { turns: turn })
            await deps.onTurnPersist?.(session)
            return { state: 'completed', turns: turn }
        }

        // Tools register under their original ids; the loop matches calls by name.
        // Sanitize names on the wire (strict providers reject `@`/`/`) and translate
        // provider-echoed names back before the loop sees the assistant message.
        //
        // Compose inner→outer: gateway-metadata (per-call request id + headers),
        // multi-model fallback (walks the priority list), sanitizing. Sanitizing
        // MUST be outermost: the fallback wrapper re-emits the winning attempt into
        // a fresh stream whose result() resolves from the forwarded `done` event,
        // which still carries provider-safe names — only the outer sanitizing
        // result() runs last and maps them back to `@posthog/...`. Fallback inside
        // sanitizing → every multi-model tool call dispatches as "tool not found".
        let coreStreamFn: StreamFn = deps.streamFn ?? streamSimple
        if (deps.gatewayHeaders || deps.gatewayUsage) {
            coreStreamFn = gatewayMetadataStreamFn(coreStreamFn, session.id, deps.gatewayHeaders, turnRequestIds)
        }

        // Which model answered this turn, for the `$ai_generation` tag. Reset per
        // `turn_start`; the fallback hooks repopulate it. Single-model sessions
        // skip the wrapper → identical to today.
        let modelAttempt = 0
        let fellBackFrom: string | undefined
        if (deps.models.length > 1) {
            // Session-sticky model selection (see `spec.models.optimize_for`):
            //  - `cost` (default): pin to the model that served the first turn so
            //    its prompt cache stays warm; no cross-model failover after.
            //  - `availability`: lead with the last-served model but fail over.
            // Seed from the conversation's last assistant turn so the pin / sticky
            // lead survives a suspend→resume, not just consecutive in-process turns.
            coreStreamFn = fallbackStreamFn(
                coreStreamFn,
                deps.models,
                {
                    onAttempt: (index) => {
                        modelAttempt = index
                    },
                    onFallback: (fromIndex, fromModel, reason) => {
                        fellBackFrom = fromModel.id
                        runLog.warn({ from: fromModel.id, attempt: fromIndex, reason }, 'model.fallback')
                    },
                },
                {
                    optimizeFor: rev.spec.models.optimize_for,
                    initialServedId: lastServedModelId(session.conversation),
                }
            )
        }
        const streamFn = sanitizingStreamFn(coreStreamFn, nameToId)

        const resolvedMaxTokens = resolveMaxOutputTokens({
            modelMaxTokens: primaryModel.maxTokens,
            configOverride: deps.maxOutputTokensOverride,
            specRequested: rev.spec.limits.max_output_tokens,
            reasoning: rev.spec.reasoning,
        })
        if (resolvedMaxTokens.clamped) {
            runLog.warn(
                {
                    requested: resolvedMaxTokens.clamped.requested,
                    ceiling: resolvedMaxTokens.clamped.ceiling,
                    source: resolvedMaxTokens.clamped.source,
                    model: primaryModel.id,
                },
                'max_output_tokens.clamped'
            )
        }

        // The loop aborts on EITHER a worker shutdown or a user cancel. The two
        // controllers stay separate so the outcome can diverge (cancel →
        // completed, shutdown → suspended); this merged view is only what the
        // provider call and the per-turn stop hook watch.
        const runSignal = deps.shutdownSignal
            ? AbortSignal.any([deps.shutdownSignal, cancelController.signal])
            : cancelController.signal

        try {
            await runAgentLoop(
                [],
                context,
                {
                    // The fallback wrapper owns model selection across the list;
                    // this is the loop's identity model (primary) for any model
                    // metadata it reads outside the stream.
                    model: primaryModel,
                    apiKey: deps.apiKey,
                    maxTokens: resolvedMaxTokens.value,
                    // Primary entry's reasoning (folds in spec default); the wrapper
                    // overrides per-attempt. pi-ai ignores it for non-reasoning models.
                    reasoning: deps.models[0].reasoning,
                    convertToLlm: (messages) => messages as unknown as Message[],
                    // The loop contract requires this hook to never throw. Drain
                    // atomically from PG so a `/send` that lands during this turn
                    // either gets included here (commit before drain) or survives
                    // for the next turn (commit after drain — lands in a fresh
                    // empty column). The runner's in-memory `session.pending_inputs`
                    // is intentionally never written back from this point on; the
                    // worker's end-of-turn `update()` skips the column too. An
                    // approval marker whose dispatch fails transiently is
                    // re-appended via `inputs.appendPendingInput` so the next
                    // resume retries instead of losing the user's approval.
                    getSteeringMessages: async (): Promise<AgentMessage[]> => {
                        const pending = await deps.inputs.drainPendingInputs(session.id)
                        if (pending.length === 0) {
                            return []
                        }
                        const out: ConversationMessage[] = []
                        const kept: ConversationMessage[] = []
                        for (const msg of pending) {
                            // Interactive client-tool result marker (from /send).
                            const clientToolResult = parseClientToolResultMarker(
                                typeof msg.content === 'string'
                                    ? msg.content
                                    : Array.isArray(msg.content) &&
                                        msg.content.length === 1 &&
                                        msg.content[0].type === 'text'
                                      ? msg.content[0].text
                                      : ''
                            )
                            if (clientToolResult) {
                                const isError = 'error' in clientToolResult
                                const envelope: Record<string, unknown> = isError
                                    ? {
                                          call_id: clientToolResult.call_id,
                                          ok: false,
                                          error: clientToolResult.error,
                                      }
                                    : {
                                          call_id: clientToolResult.call_id,
                                          ok: true,
                                          result: clientToolResult.result,
                                      }
                                const wake: ConversationMessage = {
                                    role: 'user',
                                    content: [{ type: 'text', text: JSON.stringify(envelope) }],
                                    timestamp: msg.timestamp,
                                }
                                out.push(wake)
                                await emit('client_tool_result', {
                                    call_id: clientToolResult.call_id,
                                    ...(isError
                                        ? { error: clientToolResult.error }
                                        : { result: clientToolResult.result }),
                                })
                                continue
                            }
                            const requestId = approvalMarkerRequestId(msg)
                            if (!requestId) {
                                // Plain steering input (e.g. /send) — consume it.
                                out.push(msg)
                                if (msg.role === 'user') {
                                    // Echo to live SSE consumers so the optimistic local
                                    // bubble can be reconciled with the server-confirmed
                                    // conversation position. message_end appends to
                                    // session.conversation; this event mirrors it for
                                    // anyone reading the live stream.
                                    await emit('user_message', {
                                        text: typeof msg.content === 'string' ? msg.content : '',
                                        sender: msg.sender ?? null,
                                        timestamp: msg.timestamp,
                                    })
                                }
                                continue
                            }
                            try {
                                const row = await deps.approvals.get(requestId)
                                // Drop markers that aren't a live, in-flight approval
                                // for THIS session. The session_id check is a security
                                // boundary: /send appends caller-controlled strings to
                                // pending_inputs and the request id is exposed via SSE,
                                // so without it one session could inject another's
                                // approval id and hijack its dispatch.
                                if (!row || row.session_id !== session.id || row.state !== 'approving') {
                                    runLog.warn(
                                        {
                                            requestId,
                                            rowState: row?.state ?? 'missing',
                                            sameSession: row?.session_id === session.id,
                                        },
                                        'approval.marker.dropped'
                                    )
                                    continue
                                }
                                const t0 = Date.now()
                                // dispatchApprovedResult marks the row dispatched as its
                                // commit point. If it throws after the tool ran but
                                // before that mark lands, keeping the marker can
                                // re-execute on resume — a known transient-failure
                                // window; full idempotency would need a transactional
                                // dispatch (tracked follow-up).
                                const d = await dispatchApprovedResult({
                                    approvals: deps.approvals,
                                    // A proxy-routed row is keyed `<prefix>__<remoteName>` (the gate
                                    // re-keyed onto the underlying tool) but its executor is the
                                    // connection's `call_tool`, whose args are the row's stored args.
                                    // resolveApprovedExecutor falls back to it so the approved call
                                    // actually replays instead of erroring "unknown tool".
                                    realExecute: resolveApprovedExecutor(row.tool_name, realExecute, mcpProxyCallTools),
                                    row,
                                })
                                // Secure the wake before observability so a failing
                                // emit/analytics can't strand an already-dispatched call.
                                out.push(d.wake)
                                try {
                                    const span = turn + 1
                                    await emit('tool_call', {
                                        name: d.toolName,
                                        args: d.args,
                                        id: d.toolCallId,
                                        approved: true,
                                    })
                                    await emit('tool_result', {
                                        name: d.toolName,
                                        id: d.toolCallId,
                                        ok: !d.isError,
                                        error: d.error,
                                        approval: { request_id: d.requestId, state: 'approved' },
                                    })
                                    await analytics.write([
                                        {
                                            kind: 'span',
                                            ts: new Date().toISOString(),
                                            team_id: session.team_id,
                                            application_id: session.application_id,
                                            revision_id: rev.id,
                                            session_id: session.id,
                                            turn: span,
                                            span_id: toolSpanId(session.id, span, d.toolCallId),
                                            parent_span_id: generationSpanId(session.id, span),
                                            distinct_id: distinctId,
                                            tool_name: d.toolName,
                                            tool_call_id: d.toolCallId,
                                            input: d.args,
                                            output: d.isError ? null : (d.output ?? null),
                                            latency_ms: Date.now() - t0,
                                            is_error: d.isError,
                                            error: d.error,
                                        },
                                    ])
                                } catch (obsErr) {
                                    runLog.warn(
                                        { requestId, err: (obsErr as Error).message },
                                        'approval.observability_failed'
                                    )
                                }
                            } catch (err) {
                                // Transient failure (e.g. a DB blip) — keep the marker
                                // so a later resume retries rather than losing the
                                // user's approval.
                                runLog.warn({ requestId, err: (err as Error).message }, 'approval.marker.retry')
                                kept.push(msg)
                            }
                        }
                        // Re-append transient-failure entries so the next
                        // turn retries. Goes back through the same atomic
                        // append path `/send` uses — interleaves cleanly
                        // with any concurrent mid-turn writes.
                        for (const msg of kept) {
                            try {
                                await deps.inputs.appendPendingInput(session.id, msg)
                            } catch (err) {
                                runLog.warn(
                                    { err: (err as Error).message },
                                    'pending_inputs.requeue_failed — entry lost'
                                )
                            }
                        }
                        return out as unknown as AgentMessage[]
                    },
                    shouldStopAfterTurn: async (): Promise<boolean> => {
                        if (runSignal.aborted) {
                            return true
                        }
                        if (turn >= rev.spec.limits.max_turns) {
                            stoppedByCap = true
                            return true
                        }
                        return false
                    },
                },
                sink,
                runSignal,
                streamFn
            )
        } catch (err) {
            const e = err as Error & { name?: string }
            // A user cancel beats a shutdown: it persists the partial reply and
            // reopens the session (`completed`) rather than re-queuing it.
            if (cancelController.signal.aborted) {
                return await finishInterrupted()
            }
            if (e.name === 'AbortError' || deps.shutdownSignal?.aborted) {
                return { state: 'suspended', reason: 'shutdown', turns: turn }
            }
            runLog.error({ turn, err: e.message, ...errorContext() }, 'loop.failed')
            await emitFailure(e.message ?? 'loop_error', { turns: turn, ...errorContext() })
            return { state: 'failed', reason: e.message ?? 'loop_error', turns: turn }
        }

        // Stamps the failure source (gateway vs direct provider) + model id on
        // every error log/event so operators can tell at a glance whether a
        // mystery `400 status code (no body)` came from the gateway or the
        // upstream provider. A hoisted declaration so the loop's catch block
        // above can call it too. Closes over `deps`.
        function errorContext(): Record<string, unknown> {
            return {
                source: deps.gatewayHeaders ? 'ai_gateway' : 'provider',
                model: primaryModel.id,
                provider: primaryModel.provider,
                api: primaryModel.api,
            }
        }

        // One `$ai_trace` per session at terminal outcome — gives LLM Analytics a
        // named trace (agent name) + input/output state on top of the per-turn
        // generations/spans that already share this `$ai_trace_id`. Skipped on
        // `suspended` (the session resumes and ends for real later). Best-effort.
        const writeTrace = async (): Promise<void> => {
            await analytics.write([
                {
                    kind: 'trace',
                    ts: new Date().toISOString(),
                    team_id: session.team_id,
                    application_id: session.application_id,
                    revision_id: rev.id,
                    session_id: session.id,
                    turn,
                    span_id: session.id,
                    distinct_id: distinctId,
                    trace_name: deps.applicationName ?? `agent:${session.application_id}`,
                    input_state: traceInput,
                    output_state: lastOutput,
                },
            ])
        }

        // Outcome derivation — order matters (cancel beats shutdown beats a
        // stale terminal state). A cancel caught between turns lands here (the
        // loop returned cleanly rather than throwing); `finishInterrupted` is a
        // no-op for the already-finalized turn and just reopens as `completed`.
        let outcome: RunOutcome
        if (cancelController.signal.aborted) {
            outcome = await finishInterrupted()
        } else if (deps.shutdownSignal?.aborted || lastStopReason === 'aborted') {
            outcome = { state: 'suspended', reason: 'shutdown', turns: turn }
        } else if (lastControl?.kind === 'close') {
            await emit('closed', { turns: turn, summary: lastControl.summary })
            outcome = { state: 'closed', summary: lastControl.summary, turns: turn }
        } else if (lastStopReason === 'error') {
            runLog.error({ turn, reason: lastError, ...errorContext() }, 'model.error')
            await emitFailure(lastError ?? 'model_error', { turns: turn, ...errorContext() })
            outcome = { state: 'failed', reason: lastError ?? 'model_error', turns: turn }
        } else if (lastStopReason === 'length') {
            await emitFailure('output_truncated', { turns: turn, ...errorContext() })
            outcome = { state: 'failed', reason: 'output_truncated', turns: turn }
        } else if (stoppedByCap && lastTurnContinued) {
            await emitFailure('max_turns_exceeded', { turns: turn })
            outcome = { state: 'failed', reason: 'max_turns_exceeded', turns: turn }
        } else {
            await emit('completed', { turns: turn })
            outcome = { state: 'completed', turns: turn }
        }
        if (outcome.state !== 'suspended') {
            await writeTrace()
        }
        return outcome
    } finally {
        tearDownClientDispatch()
        // Guarantee the "working" status never lingers past the run (e.g. a
        // turn that ended without prose, or a thrown loop).
        await slackStatus?.clear()
    }
}

/** First text block of a tool result, used for the error string in spans/events. */
function resultText(result: { content?: Array<{ type: string; text?: string }> } | undefined): string {
    const block = result?.content?.find((c) => c.type === 'text')
    return block?.text ?? 'error'
}

/**
 * Wrap a StreamFn so provider-bound tool names are sanitized to the
 * `^[a-zA-Z0-9_-]{1,128}$` form strict providers require, and the names a
 * provider echoes back in tool calls are translated to the original ids the
 * loop matches against.
 *
 * The actual mutation lives in `sanitizeOutboundContext` (every outbound
 * surface that carries a tool id) and `translateAssistantNamesBack` (the
 * result echo). Routing them through these two functions means every new
 * tool-id-bearing field a provider starts validating gets caught in one
 * place — the `sanitizingStreamFn` itself is just composition.
 */
function sanitizingStreamFn(base: StreamFn, safeToOriginal: Map<string, string>): StreamFn {
    return async (model, context, options) => {
        const stream = await base(model, sanitizeOutboundContext(context), options)
        const result = async (): Promise<AssistantMessage> =>
            translateAssistantNamesBack(await stream.result(), safeToOriginal)
        return new Proxy(stream, {
            get(target, prop, receiver) {
                if (prop === 'result') {
                    return result
                }
                const value = Reflect.get(target, prop, receiver)
                return typeof value === 'function' ? value.bind(target) : value
            },
        })
    }
}

/**
 * Rewrite every tool-id-bearing field in an outbound context to the
 * provider-safe form. Currently:
 *   - `context.tools[].name` — declarations the provider validates against.
 *   - `context.messages[]` — historical assistant `toolCall` names + the
 *     paired `toolResult.toolName` from prior turns. Strict providers
 *     (e.g. OpenAI Responses, `^[a-zA-Z0-9_-]+$`) reject the original
 *     `@posthog/query` shape in this position too, so without rewriting
 *     turn 2 fails with a 400 even though turn 1 went through fine.
 *
 * Any new tool-id-bearing field a future pi-ai version starts sending must
 * be added here — that's the load-bearing point of the consolidation.
 * `provider-safe-names-coverage.test.ts` runs a worst-case fixture (tool
 * declaration + historical toolCall + historical toolResult) through this
 * function to lock the contract.
 */
export function sanitizeOutboundContext<T extends { tools?: Array<{ name: string }>; messages?: Message[] }>(
    context: T
): T {
    // Provider-wire projection (the tool schemas the model sees), NOT the
    // executable dispatch array — the `{ ...t }` spread drops the gate brand.
    // If you ever dispatch off this result, re-gate it first.
    return {
        ...context,
        tools: context.tools?.map((t) => ({ ...t, name: providerSafeName(t.name) })),
        messages: context.messages?.map(sanitizeMessageNames),
    }
}

/**
 * Inverse of the outbound name rewrite for the assistant's own reply: the
 * loop matches tool calls by their ORIGINAL id, so any `toolCall.name` the
 * provider echoed back in the assistant message needs to be translated
 * before the loop sees it. Anything not in the map (e.g. the faux provider
 * echoing the original verbatim) passes through unchanged.
 */
export function translateAssistantNamesBack(
    msg: AssistantMessage,
    safeToOriginal: Map<string, string>
): AssistantMessage {
    return {
        ...msg,
        content: msg.content.map((b) =>
            b.type === 'toolCall' ? { ...b, name: safeToOriginal.get(b.name) ?? b.name } : b
        ),
    }
}

/**
 * Stamp `Idempotency-Key` + any caller-supplied gateway headers
 * (`X-PostHog-Distinct-Id`, `X-PostHog-Trace-Id`) on every outbound model call,
 * and capture the gateway's settlement reference into `turnRequestIds` (keyed
 * by the outbound-call counter) so the sink can fetch settled cost via
 * `GET /v1/usage/<id>` after `turn_end`.
 *
 * Idempotency-Key MUST be unique per outbound call. `outboundTurn` is a
 * per-`runSession` counter that resets to 0 on every resume, so a key of just
 * `agent:<session>:<turn>` collides across turns: the first call of every
 * follow-up reuses `agent:<session>:1`, which the gateway already has cached
 * under its 24h Idempotency-Key window from the session's first turn, so the
 * follow-up replays that stale response with no output (0 tokens). The per-call
 * `randomUUID()` nonce keeps it unique across resumes yet stable within a call,
 * so pi-ai's SDK-level retries on transient 5xx still collapse onto one billed
 * row.
 *
 * The usage lookup keys off the GATEWAY's id, not ours. The gateway mints its
 * own settlement reference server-side — a client-chosen id would let a caller
 * collapse every debit as a duplicate — and returns it in the response header
 * named by `GATEWAY_REQUEST_ID_HEADER` (agent-shared's `gateway-wire`); it
 * ignores any inbound `X-Request-Id`. We read it back via
 * `extractGatewayRequestId` off pi-ai's `onResponse` (header keys are
 * lowercased) — the SAME function `gateway-client.ts`'s settled-cost lookup
 * builds its URL from (`gatewayUsagePath`), so the two sides can't key on
 * different ids. A missing header (no `onResponse`, gateway misroute) just
 * leaves the turn's entry unset → cost merge is skipped (fail-open).
 */
function gatewayMetadataStreamFn(
    base: StreamFn,
    sessionId: string,
    gatewayHeaders: Record<string, string> | undefined,
    turnRequestIds: Map<number, string>
): StreamFn {
    let outboundTurn = 0
    return async (model, context, options) => {
        outboundTurn++
        const turnIndex = outboundTurn
        const idempotencyKey = `agent:${sessionId}:${turnIndex}:${randomUUID()}`
        const priorOnResponse = options?.onResponse
        return base(model, context, {
            ...options,
            headers: { ...gatewayHeaders, ...options?.headers, 'Idempotency-Key': idempotencyKey },
            onResponse: async (response, m) => {
                const id = extractGatewayRequestId(response.headers)
                if (id) {
                    turnRequestIds.set(turnIndex, id)
                }
                await priorOnResponse?.(response, m)
            },
        })
    }
}

/**
 * Rewrite tool names embedded in a historical Message so they match the
 * provider-safe form the live request will declare. Untyped to avoid a
 * tight coupling to pi-ai's Message union — we touch only the two fields
 * that carry a tool id, copy everything else through, and leave non-tool
 * messages unchanged.
 */
function sanitizeMessageNames(message: Message): Message {
    const m = message as unknown as { role?: string; toolName?: unknown; content?: unknown }
    if (m.role === 'toolResult' && typeof m.toolName === 'string') {
        return { ...message, toolName: providerSafeName(m.toolName) } as Message
    }
    if (m.role === 'assistant' && Array.isArray(m.content)) {
        return {
            ...message,
            content: (m.content as Array<{ type?: string; name?: string }>).map((b) =>
                b && b.type === 'toolCall' && typeof b.name === 'string' ? { ...b, name: providerSafeName(b.name) } : b
            ),
        } as Message
    }
    return message
}
