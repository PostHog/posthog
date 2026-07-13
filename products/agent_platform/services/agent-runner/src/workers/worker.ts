/**
 * Long-running worker: claim sessions from the queue, run turns, persist
 * progress after every turn, hand off cleanly on shutdown.
 *
 * Concurrency model — agents are largely I/O-bound (LLM HTTP, tool HTTP,
 * sandbox round-trips), so one worker process keeps up to `maxConcurrency`
 * sessions in flight at once. The loop awaits `Promise.race` on the
 * inflight set when at capacity, so a single finishing session
 * immediately frees one slot and the next claim fires — steady-state,
 * not a fill-and-drain wave. The PG queue's SELECT FOR UPDATE SKIP
 * LOCKED protects against any worker (in this process or any other)
 * double-claiming.
 *
 * Shutdown semantics — `stop()` aborts the shared `shutdownController`:
 *   - in-flight pi-ai calls receive the AbortSignal and cancel cleanly
 *   - `runSession()` returns `state: suspended` for each in-flight session
 *   - state goes back to `queued`; any sibling worker picks it up later
 *
 * pending_inputs is read by `runSession()` at turn start. /send calls land
 * there via the ingress → `queue.appendPendingInput()` path.
 */

import type { Model } from '@earendil-works/pi-ai'

import {
    AgentSession,
    AnalyticsSink,
    ApprovalStore,
    buildAskerIdentity,
    BundleStore,
    categorize,
    createLogger,
    CredentialBroker,
    IdentityCredentialStore,
    IdentityLinkStateStore,
    IdentityStore,
    FailureNotifier,
    filterServableEntries,
    GatewayCatalog,
    GatewayClient,
    getSecretAllowedHosts,
    HttpFetcher,
    LogSink,
    McpConnectionStore,
    MemoryStore,
    modelPolicyToList,
    TabularStore,
    WebSearchProvider,
    RevisionStore,
    SandboxInstanceStore,
    SandboxPool,
    SecretBroker,
    SessionEventBus,
    SessionQueue,
    userFacingMessage,
} from '@posthog/agent-shared'

import { runSession } from '../loop/driver'
import { McpTransportFactory, openMcpClients } from '../loop/mcp-clients'
import * as metrics from '../metrics'
import { resolveModelCached } from '../models/pi-client'

const log = createLogger('worker')

export interface WorkerDeps {
    queue: SessionQueue
    revisions: RevisionStore
    bundle: BundleStore
    sandboxes: SandboxPool
    broker: SecretBroker
    /** Resolved per-application secrets — wire from the team's encrypted env. */
    resolveSecrets: (session: AgentSession) => Promise<Record<string, string>>
    /**
     * Resolve a single model-id string (one entry of the resolved policy list)
     * to a concrete pi-ai Model. Defaults to `resolveModelCached` which works
     * for built-in providers. Override for custom-endpoint models (ai-gateway)
     * or test faux models. Applied per-entry across `modelPolicyToList(spec)`.
     */
    resolveModel?: (specModel: string) => Model<string>
    /** Served-model catalog. Filters the resolved model list to servable models
     *  before dispatch and feeds `ToolContext` for the models tool. */
    gatewayCatalog?: GatewayCatalog
    /**
     * Per-session API key resolver. The resolved key is passed to the driver's
     * loop config; defaults to no key. On the ai-gateway path this returns
     * the owning team's `phc_` project key (via `TeamApiKeyResolver`); on the
     * direct path it returns the boot-time `defaultApiKeyFromConfig` (Anthropic
     * / OpenAI). The driver streams through `streamSimple` and there's no
     * client-level default anymore, so the key has to arrive here per-session.
     */
    resolveApiKey?: (session: AgentSession) => Promise<string | undefined> | string | undefined
    /**
     * Per-session static HTTP headers stamped on every outbound pi-ai call.
     * On the ai-gateway path this carries `X-PostHog-Distinct-Id` +
     * `X-PostHog-Trace-Id` so gateway-emitted `$ai_generation` events
     * attribute correctly. The driver's `gatewayMetadataStreamFn` wrapper
     * merges these with a per-turn `Idempotency-Key` + `X-Request-Id` of
     * the form `agent:<session>:<turn>` before pi-ai sees them.
     */
    resolveGatewayHeaders?: (session: AgentSession) => Record<string, string> | undefined
    /**
     * Per-session gateway read client + the team's `phc_` bearer. When set,
     * the driver fetches `GET /v1/usage/<request_id>` after every turn
     * (using the id stamped by `gatewayMetadataStreamFn`) and merges
     * gateway-computed cost into `usage_total.cost_total`. Best-effort:
     * transient fetch failures + NaN bodies are logged and skipped so a
     * gateway blip can't strand a turn.
     */
    resolveGatewayUsage?: (
        session: AgentSession
    ) =>
        | Promise<{ client: GatewayClient; phc: string } | undefined>
        | { client: GatewayClient; phc: string }
        | undefined
    /**
     * Lifecycle event bus. Runner publishes session_started / turn_started /
     * assistant_text / tool_call / tool_result / completed / waiting / failed
     * events here. Chat `/listen` SSE consumes these. Required — there is no
     * in-memory fallback; tests wire a real Redis bus with a per-cluster prefix.
     */
    bus: SessionEventBus
    /**
     * Optional structured-log sink. Mirrors the bus events into a
     * persistent store (ClickHouse via Kafka in prod).
     */
    logs: LogSink
    /**
     * Optional LLM analytics sink. Production wires `KafkaAnalyticsSink`
     * to the dedicated `agent_ai_events` topic. Tests default to noop.
     */
    analytics?: AnalyticsSink
    /**
     * Optional durable sandbox-instance log. When present the worker
     * writes a row at acquire and updates it at release / failure, so a
     * sibling worker or the janitor can reap orphans after a crash.
     * Production wires `PgSandboxInstanceStore`; tests can leave it out.
     */
    sandboxInstances?: SandboxInstanceStore
    /**
     * Max concurrent in-flight sessions per worker process. Default 8.
     * Tune against memory / sandbox-pool size / LLM rate limits.
     */
    maxConcurrency?: number
    /** Operator override (AGENT_MAX_OUTPUT_TOKENS); clamps per-turn max_tokens below model ceiling. */
    maxOutputTokens?: number
    /**
     * True on the ai-gateway path: the gateway emits the `$ai_generation`
     * (settled cost + forwarded attribution), so the runner suppresses its
     * duplicate. pi-ai's `cost.*` estimates are never used regardless.
     */
    gatewayEmitsGenerations?: boolean
    /**
     * Approval-gated tools store. MANDATORY and
     * fail-closed: `requires_approval` in spec.tools is a security control, so
     * the store must always be wired — an unwired store silently disables every
     * gate (the bug this used to be). The `Worker` constructor throws when it's
     * missing; there is no mock / in-memory variant by design.
     */
    approvals: ApprovalStore
    /**
     * Builds the deep link the synthetic queued tool_result surfaces to
     * the model. Wire from config so prod hits the real domain. Takes the
     * agent slug so the link can carry `?agent=<slug>` — the deep-link
     * approval modal needs it to address the (slug-routed) ingress directly.
     */
    buildApprovalUrl?: (requestId: string, slug: string) => string
    /**
     * S3-backed memory store for `@posthog/memory-*` tools. Wired from
     * AGENT_MEMORY_S3_* config; unset disables memory tools.
     */
    memoryStore?: MemoryStore
    /** Deterministic tabular store for `@posthog/table-*` tools; same S3 config as memory. */
    tabularStore?: TabularStore
    /**
     * Web-search provider chain for `@posthog/web-search`, built from
     * AGENT_WEB_SEARCH_* config at boot. Threaded onto each session's
     * ToolContext. Empty / absent → the tool is gated out of the session.
     */
    webSearchProviders?: readonly WebSearchProvider[]
    /**
     * Per-session credential broker, populated by ingress at /run + /send.
     * The runner passes this through to `runSession` → tool deps →
     * `ToolContext.credentials.resolve(target)`. Optional — tests can
     * leave unset; tools that try to resolve get null and degrade.
     */
    credentialBroker?: CredentialBroker
    /**
     * Per-asker identity linking (spec.identity_providers). Passed through to
     * `runSession` → `ctx.identity`. Omit to disable identity tools.
     */
    identityCredentials?: IdentityCredentialStore
    identityLinks?: IdentityLinkStateStore
    identities?: IdentityStore
    /** OAuth callback base; `/link/<provider>/callback` is appended. */
    linkRedirectBaseUrl?: string
    /**
     * Override the MCP transport factory. Defaults to
     * `StreamableHTTPClientTransport`. The e2e harness substitutes an
     * `InMemoryTransport`-paired factory so tests don't have to bind a
     * localhost port; prod can also override to wrap the transport in
     * instrumentation / retry middleware.
     */
    mcpTransportFactory?: McpTransportFactory
    /**
     * Shared-credential MCP resolver (`spec.mcps[].connection`). The worker binds
     * it to the session's `team_id`. Omit to disable the connection path.
     */
    mcpConnections?: McpConnectionStore
    /**
     * Dev-only bearer forwarded to `openMcpClients`. See `OpenMcpClientsDeps`.
     * Sourced from `AGENT_DEV_MCP_BEARER_TOKEN`; the runner's `index.ts`
     * refuses to set this when NODE_ENV=production.
     */
    devMcpBearerToken?: string
    /**
     * Outbound HTTP client. Forwarded into `runSession` → `AgentToolDeps`
     * → `ToolContext.http`; also handed to `openMcpClients` so the MCP
     * SDK's `StreamableHTTPClientTransport` routes through the same
     * dispatcher. Wired at the runner entrypoint from `HTTPS_PROXY` env
     * (smokescreen in prod, direct in dev).
     */
    http: HttpFetcher
    /**
     * Base URL for the PostHog API the agent-applications-* tools call
     * against. Forwarded into `ToolContext.posthogApiBaseUrl`.
     */
    posthogApiBaseUrl: string
    /**
     * Out-of-band notifier fired on terminal failure (pre-runSession catch +
     * in-loop `emitFailure`). Production wires `TriggerAwareFailureNotifier`
     * with a `SlackFailureNotifier` registered for slack-triggered sessions
     * so a crashed session reaches back to the originating thread with a
     * sanitized message. Optional — when unset, terminal failures still
     * update PG / bus / log_entries identically.
     */
    failureNotifier?: FailureNotifier
}

export class Worker {
    private running = false
    private readonly shutdownController = new AbortController()
    private readonly maxConcurrency: number
    /** session_id → in-flight runOne promise. */
    private readonly inflight = new Map<string, Promise<void>>()

    constructor(private readonly deps: WorkerDeps) {
        // Fail-closed: the approval store is a security control, not an optional
        // capability. Boot crashes here rather than silently running every
        // `requires_approval` tool ungated. Guarded at runtime (not just the
        // type) so a JS caller / test that omits it can't slip a gate-less
        // worker into production.
        if (!deps.approvals) {
            throw new Error(
                'WorkerDeps.approvals is required — refusing to start with approval gating disabled. Wire a PgApprovalStore.'
            )
        }
        this.maxConcurrency = Math.max(1, deps.maxConcurrency ?? 8)
        metrics.maxConcurrency.set(this.maxConcurrency)
        metrics.inflightSessions.set(0)
    }

    /** Signal a graceful shutdown. In-flight sessions suspend back to PG. */
    async stop(): Promise<void> {
        this.running = false
        this.shutdownController.abort()
        // Let outstanding sessions persist their suspended state before the
        // process exits.
        await Promise.allSettled(this.inflight.values())
    }

    get shutdownSignal(): AbortSignal {
        return this.shutdownController.signal
    }

    /** setTimeout that resolves early if shutdown is signalled, so a backoff can't stall drain. */
    private async sleep(ms: number): Promise<void> {
        if (ms <= 0 || this.shutdownController.signal.aborted) {
            return
        }
        await new Promise<void>((resolve) => {
            const signal = this.shutdownController.signal
            const onAbort = (): void => {
                clearTimeout(timer)
                resolve()
            }
            const timer = setTimeout(() => {
                signal.removeEventListener('abort', onAbort)
                resolve()
            }, ms)
            signal.addEventListener('abort', onAbort, { once: true })
        })
    }

    /**
     * Main loop. Keeps up to `maxConcurrency` sessions in flight. Returns when
     * (a) `iterations` claimed sessions have been processed, (b) the shutdown
     * signal fires, or (c) `stop()` is called.
     */
    async loop(opts?: {
        iterations?: number
        claimTimeoutMs?: number
        claimBackoffBaseMs?: number
        claimBackoffMaxMs?: number
    }): Promise<void> {
        this.running = true
        const targetClaims = opts?.iterations ?? Infinity
        const claimMs = opts?.claimTimeoutMs ?? 1_000
        // Exponential backoff for consecutive claim failures. A bad DB state
        // (pool unreachable, malformed row) makes `claim()` throw immediately,
        // so without this the loop spins hot — re-querying with no delay,
        // saturating PG and flooding logs. Resets the instant a claim succeeds.
        const backoffBaseMs = opts?.claimBackoffBaseMs ?? 500
        const backoffMaxMs = opts?.claimBackoffMaxMs ?? 30_000
        let consecutiveClaimFailures = 0
        let claimed = 0

        while (this.running && claimed < targetClaims && !this.shutdownController.signal.aborted) {
            // Wait for ONE open slot so we maintain steady-state concurrency.
            // Each promise in `inflight` is chained with `.catch()` below, so
            // it can only resolve — never reject — making Promise.race safe
            // without the all-settled drain that used to wedge utilization
            // into a wave pattern (fill to N → wait for slowest → fill again).
            // The winning promise's `.finally` has already removed it from
            // the map by the time we resume here, so size has decremented.
            while (this.inflight.size >= this.maxConcurrency) {
                await Promise.race(this.inflight.values())
            }
            if (!this.running || this.shutdownController.signal.aborted || claimed >= targetClaims) {
                break
            }
            let session: AgentSession | null
            try {
                session = await this.deps.queue.claim(claimMs)
                consecutiveClaimFailures = 0
                metrics.consecutiveClaimFailures.set(0)
            } catch (err) {
                // Transient PG error / malformed row mapping. Log and back off
                // before retrying — without this guard a single bad row crashes
                // the worker, and without the backoff a persistent DB fault
                // spins the loop hot. Equal jitter keeps the floor growing while
                // de-syncing retries across pods recovering together.
                consecutiveClaimFailures++
                metrics.claimFailures.inc()
                metrics.consecutiveClaimFailures.set(consecutiveClaimFailures)
                const window = Math.min(backoffMaxMs, backoffBaseMs * 2 ** (consecutiveClaimFailures - 1))
                const delayMs = Math.round(window / 2 + Math.random() * (window / 2))
                log.error(
                    {
                        err: (err as Error).message,
                        stack: (err as Error).stack,
                        consecutiveClaimFailures,
                        backoffMs: delayMs,
                    },
                    'claim.failed'
                )
                await this.sleep(delayMs)
                continue
            }
            if (!session) {
                continue
            }
            const claimedSession = session
            claimed++
            const p = this.runOne(claimedSession)
                .catch((err) => {
                    // runOne already has an inner try/catch; this is a
                    // belt-and-braces guard so an unexpected rejection
                    // (e.g. queue.update failing in the catch arm) doesn't
                    // surface as an unhandledRejection on the inflight map.
                    log.error(
                        { session_id: claimedSession.id, err: (err as Error).message },
                        'runOne.unhandled_rejection'
                    )
                })
                .finally(() => {
                    this.inflight.delete(claimedSession.id)
                    metrics.inflightSessions.set(this.inflight.size)
                })
            this.inflight.set(claimedSession.id, p)
            metrics.inflightSessions.set(this.inflight.size)
        }

        // Drain any still-in-flight sessions before returning so the caller
        // can rely on "loop() done == all my sessions persisted."
        await Promise.allSettled(this.inflight.values())
    }

    async runOne(session: AgentSession): Promise<void> {
        const sLog = log.child({ session_id: session.id, application_id: session.application_id })
        sLog.debug({ revision_id: session.revision_id }, 'session.claim')
        const runStartedAt = Date.now()
        let sandbox = null
        let sandboxInstanceId: string | null = null
        // `mcpClose` is the batched closer returned by `openMcpClients`. The
        // worker is the owner: it opens at session start, hands the client
        // list off to `runSession`, and closes in `finally` so a crashed
        // session can't strand open transports.
        let mcpClose: (() => Promise<void>) | null = null
        let openedMcpClients: Awaited<ReturnType<typeof openMcpClients>>['clients'] = []
        try {
            // Pre-flight (revision load, secrets, sandbox acquire) lives INSIDE
            // the try so a malformed revision.spec (ZodError out of PgRevisionStore),
            // a missing tool file, a decryption failure, or a sandbox-pool exhaustion
            // doesn't escape this method and crash the outer worker loop.
            // The single session gets marked failed; siblings keep running.
            const rev = await this.deps.revisions.getRevision(session.revision_id)
            if (!rev) {
                sLog.warn({}, 'session.revision_missing — marking failed')
                await this.deps.queue.update(session.id, { state: 'failed' })
                return
            }
            // Friendly name for the session's `$ai_trace` (LLM Analytics). Best-
            // effort — a missing app just falls back to the id in the driver.
            const application = await this.deps.revisions.getApplication(session.application_id).catch(() => null)
            const secrets = await this.deps.resolveSecrets(session)
            const customTools = rev.spec.tools.filter((t) => t.kind === 'custom')
            if (customTools.length > 0) {
                const loads = await Promise.all(
                    customTools.map(async (t) => ({
                        id: t.id,
                        compiledJs: await this.deps.bundle.readText(rev.id, `${t.path.replace(/\/$/, '')}/compiled.js`),
                        schemaJson: JSON.parse(
                            await this.deps.bundle
                                .readText(rev.id, `${t.path.replace(/\/$/, '')}/schema.json`)
                                .catch(() => '{}')
                        ),
                    }))
                )
                const nonces = this.deps.broker.mintSessionMap(session.id, secrets)
                // Insert a provisioning row BEFORE we ask the pool — if acquireForSession
                // hangs / crashes we still have a row to reap.
                if (this.deps.sandboxInstances) {
                    const created = await this.deps.sandboxInstances.create({
                        team_id: session.team_id,
                        application_id: session.application_id,
                        revision_id: rev.id,
                        session_id: session.id,
                        provider_kind: this.deps.sandboxes.kind,
                    })
                    sandboxInstanceId = created.id
                }
                const sandboxStartedAt = Date.now()
                try {
                    sandbox = await this.deps.sandboxes.acquireForSession({
                        sessionId: session.id,
                        teamId: session.team_id,
                        tools: loads,
                        nonces,
                        sessionTimeoutMs: rev.spec.limits.max_wall_seconds * 1000,
                        limits: {
                            // wallMs duplicates sessionTimeoutMs above; pools that
                            // honor SandboxLimits.wallMs (e.g. InProcess for tests)
                            // also see it here.
                            wallMs: rev.spec.limits.max_wall_seconds * 1000,
                            memoryMb: rev.spec.limits.max_memory_mb,
                            cpuCores: rev.spec.limits.max_cpu_cores,
                        },
                    })
                    metrics.sandboxAcquire
                        .labels({ provider: this.deps.sandboxes.kind, outcome: 'ok' })
                        .observe((Date.now() - sandboxStartedAt) / 1000)
                    if (sandboxInstanceId) {
                        // Real provider id (Modal sandbox id, Docker container hash,
                        // or sessionId fallback for in-process) so the janitor
                        // reaper can look up + terminate orphans out-of-process.
                        await this.deps.sandboxInstances!.markReady(sandboxInstanceId, sandbox.providerSandboxId)
                    }
                } catch (err) {
                    metrics.sandboxAcquire
                        .labels({ provider: this.deps.sandboxes.kind, outcome: 'error' })
                        .observe((Date.now() - sandboxStartedAt) / 1000)
                    if (sandboxInstanceId) {
                        await this.deps.sandboxInstances!.markFailed(sandboxInstanceId, (err as Error).message)
                    }
                    throw err
                }
            }
            // MCP open is unconditional on `rev.spec.mcps.length`; a failure here
            // throws and falls into the outer catch (session marked failed) —
            // same all-or-nothing contract as the sandbox-acquire path. We open
            // AFTER the sandbox so the cost-of-failure on a bad MCP doesn't waste
            // a sandbox-pool slot; the order is otherwise unobservable.
            let mcpFailures: Awaited<ReturnType<typeof openMcpClients>>['failures'] = []
            if (rev.spec.mcps.length > 0) {
                // Build the per-asker resolver only when an MCP needs it (auth.provider),
                // so the common secret / BYO-token path pays nothing.
                const mcpNeedsIdentity = rev.spec.mcps.some((m) => m.auth?.provider)
                const mcpIdentity =
                    mcpNeedsIdentity && this.deps.identityCredentials && this.deps.identityLinks
                        ? await buildAskerIdentity(rev, session, {
                              credentials: this.deps.identityCredentials,
                              links: this.deps.identityLinks,
                              identities: this.deps.identities,
                              credentialBroker: this.deps.credentialBroker,
                              http: this.deps.http,
                              secret: (name) => secrets[name],
                              posthogApiBaseUrl: this.deps.posthogApiBaseUrl,
                              linkRedirectBaseUrl: this.deps.linkRedirectBaseUrl,
                              log: (level, msg, meta) => sLog[level](meta ?? {}, msg),
                          })
                        : undefined
                // Bind the connection resolver to this session's team.
                const mcpConnections = this.deps.mcpConnections
                    ? {
                          resolve: (connectionId: string) =>
                              this.deps.mcpConnections!.resolve(connectionId, session.team_id),
                      }
                    : undefined
                const opened = await openMcpClients(rev.spec.mcps, {
                    secrets,
                    secretAllowedHosts: (name) => getSecretAllowedHosts(rev.spec, name),
                    transportFactory: this.deps.mcpTransportFactory,
                    identity: mcpIdentity,
                    connections: mcpConnections,
                    devMcpBearerToken: this.deps.devMcpBearerToken,
                    log: (level, msg, meta) => sLog[level](meta ?? {}, msg),
                    http: this.deps.http,
                })
                openedMcpClients = opened.clients
                mcpClose = opened.close
                mcpFailures = opened.failures
                for (const f of mcpFailures) {
                    metrics.mcpOpenFailures.labels({ category: f.category }).inc()
                }
                // Persist the per-ref failure detail to log_entries so the
                // agent owner can debug via the session-detail page. The
                // bus + system prompt only see the coarse category — raw
                // reasons stay server-side.
                if (mcpFailures.length > 0 && this.deps.logs) {
                    const ts = new Date().toISOString()
                    await this.deps.logs
                        .write(
                            mcpFailures.map((f) => ({
                                ts,
                                team_id: session.team_id,
                                application_id: session.application_id,
                                session_id: session.id,
                                level: 'warn',
                                event: 'mcp_open_failed',
                                data: { prefix: f.ref.id, category: f.category, reason: f.devReason },
                            }))
                        )
                        .catch((logErr) =>
                            sLog.warn(
                                { err: (logErr as Error).message },
                                'session.mcp_failure_log_write_failed — session continues with degraded MCPs'
                            )
                        )
                }
            }
            // Expand the policy to a priority list, then drop entries the gateway
            // no longer serves (no-op without a catalog; never empties a non-empty
            // list — see `filterServableEntries`).
            const resolveModel = this.deps.resolveModel ?? resolveModelCached
            const catalogModels = this.deps.gatewayCatalog ? await this.deps.gatewayCatalog.list() : []
            const policyList = modelPolicyToList(rev.spec)
            if (this.deps.gatewayCatalog && catalogModels.length === 0) {
                // Fail-open: with no catalog we can't filter, so the policy list
                // ships as-authored. An empty catalog behind a *configured*
                // gateway is either a fetch that failed with no cached fallback
                // or a gateway serving nothing — both can dispatch a delisted
                // model that 400s on the first call. Surface it loudly so it's
                // not indistinguishable from a healthy run. Cleanly refusing to
                // start on a genuinely-empty (vs transiently-unreachable) catalog
                // needs a freshness signal on the catalog read — tracked as a
                // follow-up (see PR review).
                sLog.warn(
                    { policy_entries: policyList.length },
                    'model.catalog_empty_fail_open — dispatching unfiltered model policy'
                )
            }
            const policyEntries = filterServableEntries(policyList, catalogModels)
            const models = policyEntries.map((entry) => ({
                model: resolveModel(entry.model),
                reasoning: entry.reasoning,
            }))
            const apiKey = await this.deps.resolveApiKey?.(session)
            const gatewayHeaders = this.deps.resolveGatewayHeaders?.(session)
            const gatewayUsage = await this.deps.resolveGatewayUsage?.(session)
            // Bind the agent slug into the approval-link builder so the deep link
            // carries `?agent=<slug>` — the ingress-routed approval modal needs it
            // to address the agent's ingress directly.
            const buildApprovalUrl = this.deps.buildApprovalUrl
            const outcome = await runSession(rev, session, {
                models,
                apiKey,
                bundle: this.deps.bundle,
                sandbox,
                secrets,
                broker: this.deps.broker,
                bus: this.deps.bus,
                logs: this.deps.logs,
                analytics: this.deps.analytics,
                applicationName: application?.name || application?.slug,
                shutdownSignal: this.shutdownController.signal,
                getSessionState: async (id) => (await this.deps.queue.get(id))?.state ?? null,
                gatewayEmitsGenerations: this.deps.gatewayEmitsGenerations,
                gatewayHeaders,
                gatewayUsage,
                approvals: this.deps.approvals,
                buildApprovalUrl: buildApprovalUrl
                    ? (requestId) => buildApprovalUrl(requestId, application?.slug ?? '')
                    : undefined,
                memoryStore: this.deps.memoryStore,
                tabularStore: this.deps.tabularStore,
                webSearchProviders: this.deps.webSearchProviders,
                credentialBroker: this.deps.credentialBroker,
                identityCredentials: this.deps.identityCredentials,
                identityLinks: this.deps.identityLinks,
                identities: this.deps.identities,
                linkRedirectBaseUrl: this.deps.linkRedirectBaseUrl,
                mcpClients: openedMcpClients,
                mcpFailures,
                http: this.deps.http,
                posthogApiBaseUrl: this.deps.posthogApiBaseUrl,
                gatewayCatalog: this.deps.gatewayCatalog,
                maxOutputTokensOverride: this.deps.maxOutputTokens,
                inputs: this.deps.queue,
                onTurnPersist: async (s) => {
                    // Persist progress after every turn so a crash mid-loop
                    // leaves valid conversation state on disk. pending_inputs
                    // is intentionally NOT included — the runner manages it
                    // directly via `inputs.drainPendingInputs` /
                    // `appendPendingInput` against PG so a concurrent
                    // mid-turn `/send` can't be clobbered by writing back
                    // the runner's stale in-memory copy.
                    await this.deps.queue.update(s.id, {
                        conversation: s.conversation,
                        usage_total: s.usage_total,
                    })
                },
            })

            const newState: AgentSession['state'] = (() => {
                switch (outcome.state) {
                    case 'completed':
                        return 'completed'
                    case 'closed':
                        return 'closed'
                    case 'suspended':
                        // Re-queue: a sibling worker will resume from PG.
                        return 'queued'
                    case 'failed':
                        return 'failed'
                }
            })()
            sLog.debug({ outcome: outcome.state, turns: outcome.turns, newState }, 'session.done')
            // pending_inputs intentionally omitted — see onTurnPersist above.
            await this.deps.queue.update(session.id, {
                state: newState,
                conversation: session.conversation,
                usage_total: session.usage_total,
            })
            metrics.sessionOutcomes.labels({ outcome: outcome.state }).inc()
            metrics.sessionDuration.observe((Date.now() - runStartedAt) / 1000)
            metrics.sessionTurns.observe(outcome.turns)
        } catch (err) {
            // Pre-runSession failures (revision load, secrets, sandbox acquire,
            // MCP open) skip the driver's bus / log / conversation hooks. Without
            // mirroring them here the user sees a session that flips to `failed`
            // with no rendered explanation, no SSE event, and an empty assistant
            // turn — same opaque outcome a true crash would leave. Surface the
            // failure on the same three channels the in-loop `emit('failed')`
            // already covers so the console session-detail page lights up
            // identically regardless of where the failure originated.
            const e = err as Error
            const reason = e.message || 'session_failed_before_start'
            const category = categorize(reason)
            const userText = userFacingMessage(category)
            sLog.error({ err: reason, stack: e.stack, category }, 'session.crashed')
            metrics.sessionOutcomes.labels({ outcome: 'failed' }).inc()
            metrics.sessionFailures.labels({ category }).inc()
            metrics.sessionDuration.observe((Date.now() - runStartedAt) / 1000)

            // 1. Synthetic assistant message — so the user sees something in the
            //    transcript instead of their lone user turn followed by silence.
            //    Sanitized via `userFacingMessage(category)` so a docker/MCP
            //    error string doesn't leak into the conversation UI. The raw
            //    reason lives on `errorMessage` (owner-facing only) and in
            //    log_entries for the session-detail page.
            const ts = new Date().toISOString()
            session.conversation.push({
                role: 'assistant',
                content: [
                    {
                        type: 'text',
                        text: userText,
                    },
                ],
                stopReason: 'error',
                errorMessage: reason,
                timestamp: Date.now(),
            })

            // 2. Lifecycle event to the bus — /listen SSE clients render it.
            //    Deliberately empty payload: the raw `reason` can carry
            //    implementation detail (MCP transport URLs, secret-resolver
            //    error bodies, etc.) and the bus event is fanned out to
            //    every chat client connected to this session — not just
            //    the agent owner. The full reason is in log_entries (write
            //    below) for the session-detail page to surface to owners.
            //    Keep in sync with `emitFailure` in driver.ts.
            if (this.deps.bus) {
                await this.deps.bus
                    .publish({
                        session_id: session.id,
                        kind: 'failed',
                        data: {},
                        ts,
                    })
                    .catch((busErr) =>
                        sLog.warn(
                            { err: (busErr as Error).message },
                            'session.failed_event_publish_failed — session still marked failed in PG'
                        )
                    )
            }

            // 3. Structured log entry — the console session-detail page reads
            //    `log_entries` to render the per-turn event timeline.
            if (this.deps.logs) {
                await this.deps.logs
                    .write([
                        {
                            ts,
                            team_id: session.team_id,
                            application_id: session.application_id,
                            session_id: session.id,
                            level: 'error',
                            event: 'failed',
                            data: { reason, category, source: 'pre_run_session' },
                        },
                    ])
                    .catch((logErr) =>
                        sLog.warn(
                            { err: (logErr as Error).message },
                            'session.failed_log_write_failed — session still marked failed in PG'
                        )
                    )
            }

            // pending_inputs intentionally omitted — pre-runSession failures
            // happen before any drain runs, so writing the in-memory copy
            // back is a no-op at best and a clobber of a concurrent /send
            // at worst.
            await this.deps.queue.update(session.id, {
                state: 'failed',
                conversation: session.conversation,
                usage_total: session.usage_total,
            })

            // 4. Out-of-band notifier — runs AFTER queue.update so a notifier
            //    crash can't leave the row in a non-terminal state. The
            //    notifier itself contracts to swallow errors, but the catch
            //    here is belt-and-braces. For slack-triggered sessions this
            //    posts the same `userText` back to the originating thread; for
            //    every other trigger type it no-ops silently.
            if (this.deps.failureNotifier) {
                const application = await this.deps.revisions.getApplication(session.application_id).catch((appErr) => {
                    sLog.warn({ err: (appErr as Error).message }, 'session.failure_notifier_app_load_failed')
                    return null
                })
                // The notifier resolves its outbound secret (e.g. Slack bot
                // token) from the revision's `encrypted_env`, so load the
                // session's revision here — the pre-runSession `rev` may never
                // have loaded (a revision_missing failure is one path into this
                // catch). Best-effort: a missing revision just means no notice.
                const revision = await this.deps.revisions.getRevision(session.revision_id).catch((revErr) => {
                    sLog.warn({ err: (revErr as Error).message }, 'session.failure_notifier_revision_load_failed')
                    return null
                })
                if (application && revision) {
                    await this.deps.failureNotifier
                        .notify({ session, application, revision, reason, category })
                        .catch((notifyErr) =>
                            sLog.warn({ err: (notifyErr as Error).message }, 'session.failure_notifier_threw')
                        )
                } else if (application && !revision) {
                    // Revision didn't load (deleted, or this catch was entered
                    // before the revision ever loaded — a revision_missing
                    // failure is one path in). The notifier resolves its
                    // outbound secret off the revision, so it can't send without
                    // one; log at error so the skipped notice is observable
                    // rather than a silent drop.
                    sLog.error({ revision_id: session.revision_id }, 'session.failure_notifier_skipped_no_revision')
                }
            }
        } finally {
            if (sandbox) {
                await this.deps.sandboxes.release(session.id)
                if (sandboxInstanceId && this.deps.sandboxInstances) {
                    await this.deps.sandboxInstances.markTerminated(sandboxInstanceId).catch(() => undefined)
                }
            }
            if (mcpClose) {
                // Best-effort: a failing transport close shouldn't strand the
                // session. `openMcpClients` already logs per-client close
                // failures via the supplied `log`; the outer catch here just
                // guards against an unexpected throw from the batched closer.
                await mcpClose().catch((err) => sLog.warn({ err: (err as Error).message }, 'session.mcp_close_failed'))
            }
            this.deps.broker.release(session.id)
        }
    }
}
