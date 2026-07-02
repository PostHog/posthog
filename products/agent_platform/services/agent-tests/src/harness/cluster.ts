/**
 * In-process cluster harness for v2 e2e tests.
 *
 * Real everywhere except model invocation:
 *   - Postgres (agent_runtime_queue_test) — PgSessionQueue + PgRevisionStore.
 *     Schema is Django-owned (migrated before the suite); reset() truncates per test.
 *   - SeaweedFS / S3 — `S3BundleStore` + `S3MemoryStore` against the
 *     `AGENT_MEMORY_TEST_S3_*` bucket, per-cluster random prefix. No fs/in-memory
 *     bundle store — every test exercises the real multipart write + signed-URL
 *     path that prod uses.
 *   - Redis (REDIS_URL, defaults to localhost:6379) — RedisSessionEventBus
 *     with a per-cluster channel prefix so concurrent test files don't see each
 *     other's events. Same impl prod runs; in-memory bus has been removed.
 *   - Express ingress — full real route table.
 *   - Runner Worker — same loop the prod bin runs (concurrency, shutdown, pending_inputs).
 *   - Sandbox pool — InProcessSandboxPool (constructor refuses outside NODE_ENV=test).
 *   - Driver — streams through pi-ai's `streamSimple`, pointed at the faux provider.
 *
 * Mocked at the model layer ONLY: pi-ai's `faux` provider, registered once per
 * process. Each test sets its own scripted response list before firing the
 * trigger. Real-inference variants (gated by ANTHROPIC_API_KEY / etc.) skip the
 * faux setup and use a real provider Model — same harness, different model.
 */

import type { Model } from '@earendil-works/pi-ai'
import { createHmac } from 'crypto'
import { Express } from 'express'
import { Pool } from 'pg'
import request from 'supertest'

import { AuthProvider, buildApp, SessionEventBus } from '@posthog/agent-ingress'
import { buildJanitorApp } from '@posthog/agent-janitor'
import { McpTransportFactory, Worker } from '@posthog/agent-runner'
import type { AnalyticsEvent, IdentityStore, LogEntry } from '@posthog/agent-shared'
import {
    AgentApplication,
    AgentRevision,
    AgentSpecSchema,
    buildTestBundleStore,
    buildTestStore as buildMemoryTestStore,
    CredentialBroker,
    InProcessSandboxPool,
    KafkaLogSink,
    RoutingAnalyticsSink,
    newTestPrefix as newMemoryTestPrefix,
    PgApprovalStore,
    PgCredentialBroker,
    PgIdentityCredentialStore,
    PgIdentityLinkStateStore,
    PgIdentityStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    RedisSessionEventBus,
    S3BundleStore,
    S3JsonlTabularStore,
    DEV_INTERNAL_SIGNING_KEY,
    EncryptedEnvSecretResolver,
    EncryptedFields,
    HttpClient,
    type HttpFetcher,
    S3MemoryStore,
    SecretBroker,
    SecretResolver,
    TEST_S3_BUCKET,
    type WebSearchProvider,
    wipeTestPrefix as wipeMemoryTestPrefix,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { buildFauxModel, ScriptedTurn } from './faux'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'localhost:9092'

/**
 * Wrap an `HttpFetcher` so `POST /api/projects/{team}/query/` returns an
 * in-process echo of the submitted HogQL string (`results: [[query]]`,
 * `columns: ['query']`) — which `@posthog/query` maps into a single
 * `{ query }` row. Mirrors the old in-process echo client so query cases run
 * without a live Django; every other request passes straight through.
 */
function buildQueryEchoHttp(inner: HttpFetcher): HttpFetcher {
    return {
        async fetch(input, init) {
            const url = String(input)
            if (init?.method === 'POST' && /\/api\/projects\/\d+\/query\/?$/.test(url)) {
                let query = ''
                try {
                    const body = init.body ? JSON.parse(String(init.body)) : {}
                    query = body?.query?.query ?? ''
                } catch {
                    query = ''
                }
                return new Response(JSON.stringify({ results: [[query]], columns: ['query'] }), {
                    status: 200,
                    headers: { 'content-type': 'application/json' },
                })
            }
            return inner.fetch(input, init)
        },
    }
}

/**
 * Test-side `LogSink`-shaped collector backed by `KafkaLogSink`. The real
 * sink does the produce; the tap accumulates entries for assertion. Tests
 * never query ClickHouse — the materialized view is async and flakey under
 * load. Validating that produce was called with the right wire bytes is the
 * contract that prevents drift; the downstream CH path is exercised in prod.
 */
export interface CollectingLogSink {
    readonly entries: LogEntry[]
    forSession(sessionId: string): LogEntry[]
    clear(): void
}

/** One tapped `$ai_*` capture — the wire shape the routing sink would POST. */
export interface AnalyticsTapEntry {
    /** Destination project key the sink resolved for this event (`phc_team_<id>` in the harness). */
    apiKey: string | null
    /** `$ai_generation` | `$ai_span` | `$ai_trace`. */
    eventName: string
    event: AnalyticsEvent
    properties: Record<string, unknown>
}

/**
 * Test-side analytics collector. The harness wires a real `RoutingAnalyticsSink`
 * with a stub per-team resolver (`team_id → phc_team_<id>`) + a no-op client, so
 * tests assert the routing + `$ai_*` event shapes without a real PostHog. Mirrors
 * `CollectingLogSink`.
 */
export interface CollectingAnalyticsSink {
    readonly entries: AnalyticsTapEntry[]
    forSession(sessionId: string): AnalyticsTapEntry[]
    clear(): void
}

/** Deterministic 32-byte salt for the harness's `EncryptedFields`. Same key
 *  drives the credential broker and the Slack signing-secret resolver, so the
 *  encrypt/decrypt round-trip is exercised end-to-end on every test. */
const HARNESS_ENCRYPTION_SALT_KEYS = '01234567890123456789012345678901'

export interface BuildAgentInput {
    slug: string
    name?: string
    description?: string
    teamId?: number
    /** Spec input — accepts the partial shape before AgentSpecSchema applies defaults. */
    spec?: Record<string, unknown>
    files?: Record<string, string>
    /**
     * Plaintext env map. The harness Fernet-encrypts it with the same key the
     * harness's `SecretResolver` uses to decrypt, so production's
     * "decrypt at request time, look up key" path is exercised end-to-end.
     * Required for slack triggers (handler resolves `SLACK_SIGNING_SECRET_KEY`
     * here). Other triggers don't read env so this can stay undefined.
     */
    encrypted_env?: Record<string, string>
}

export interface Cluster {
    pool: Pool
    revisions: PgRevisionStore
    queue: PgSessionQueue
    bundle: S3BundleStore
    /** Per-cluster bucket prefix the bundle store is rooted at. */
    bundlePrefix: string
    bus: SessionEventBus
    identities: IdentityStore
    logs: CollectingLogSink
    /** Tapped `$ai_generation` / `$ai_span` / `$ai_trace` the runner emitted, with the resolved per-team key. */
    analytics: CollectingAnalyticsSink
    sandboxes: InProcessSandboxPool
    credentialBroker: CredentialBroker
    sandboxInstances: PgSandboxInstanceStore
    broker: SecretBroker
    /**
     * Real S3MemoryStore (SeaweedFS in dev) wired through to ToolContext for the
     * `@posthog/memory-*` tools. Per-cluster random prefix isolates concurrent
     * tests; teardown wipes the prefix.
     */
    memoryStore: S3MemoryStore
    /**
     * Real S3JsonlTabularStore (SeaweedFS in dev) wired through to ToolContext
     * for the `@posthog/table-*` tools. Shares the memory store's bucket prefix
     * so teardown wipes both at once.
     */
    tabularStore: S3JsonlTabularStore
    /**
     * The `EncryptedFields` instance the harness encrypts agent env with (and
     * the runner's secret resolver decrypts). Exposed so cases can encrypt a
     * value to stamp onto a revision's `encrypted_env`, or decrypt one to
     * assert a round-trip.
     */
    encryption: EncryptedFields
    /** The faux pi-ai Model the runner is wired with. */
    model: Model<string>
    ingress: Express
    janitor: Express
    worker: Worker
    /** Compute the (timestamp, signature) Slack would send for `rawBody`
     *  using the caller-supplied signing secret. Convenience for tests that
     *  also pass that secret into `deployAgent` via `encrypted_env`. */
    signSlack(rawBody: string, secret: string): { ts: string; sig: string }
    /** Send a signed POST to `/agents/<slug>/slack/<action>` carrying `body`
     *  as JSON, signed with `secret`. Same secret must be set in the agent's
     *  `encrypted_env[SLACK_SIGNING_SECRET]`. */
    slackPost(slug: string, action: string, body: object, secret: string): Promise<import('supertest').Response>
    /** Rearm the faux provider's response script for the next pi-ai call(s). */
    setScript(turns: ScriptedTurn[]): void
    deployAgent(input: BuildAgentInput): Promise<{ application: AgentApplication; revision: AgentRevision }>
    /** Pump the runner. Default: drain queue (up to 50 iterations). */
    drain(opts?: { iterations?: number }): Promise<void>
    /** Clean up resources. Idempotent. */
    teardown(): Promise<void>
}

export interface BuildClusterOpts {
    teamId?: number
    routingMode?: 'path' | 'domain'
    domainSuffix?: string
    /**
     * Direct resolver override — used by tests that want to exercise the
     * per-agent `encrypted_env` lookup explicitly. Without this the harness
     * wires a resolver that returns `cluster.slackSigningSecret` for every
     * lookup, which is the right default for tests that just want a Slack
     * trigger to "work end-to-end" without populating an encrypted env.
     */
    slackSigningSecretResolver?: SecretResolver
    /** Override the per-session secret resolver (defaults to empty). */
    resolveSecrets?: (sessionId: string) => Promise<Record<string, string>>
    authProvider?: AuthProvider
    /**
     * Optional initial script for the faux provider. Tests that script per-test
     * call `cluster.setScript(...)` before firing triggers.
     */
    initialScript?: ScriptedTurn[]
    /**
     * Override the model — set this to a real provider Model (e.g.
     * `getModel('anthropic', 'claude-sonnet-4-7')`) for real-inference tests.
     */
    model?: Model<string>
    /**
     * Override the MCP transport factory. Defaults to the runner's own
     * `StreamableHTTPClientTransport`. Pair an in-process `McpServer` via
     * `InMemoryTransport.createLinkedPair()` here to drive `spec.mcps[]`
     * round-trips without binding a localhost port — see
     * `cases/mcp-tools.test.ts`.
     */
    mcpTransportFactory?: McpTransportFactory
    /**
     * Substitute the outbound HTTP client the runner threads into
     * `ToolContext.http`. Tests that want to assert on outbound headers
     * or short-circuit the network pass a `{ fetch: vi.fn(...) }` here.
     * Defaults to a real `HttpClient` with no proxy (direct fetch).
     */
    http?: import('@posthog/agent-shared').HttpFetcher
    /**
     * Provider chain for `@posthog/web-search`. Forwarded onto the Worker
     * so cases that declare the tool in their spec actually see it. Empty
     * / absent (default) → the tool is gated out, matching the prod path
     * for an unconfigured deployment.
     */
    webSearchProviders?: readonly WebSearchProvider[]
}

let _pool: Pool | null = null

async function getPool(): Promise<Pool> {
    if (_pool) {
        return _pool
    }
    _pool = new Pool({ connectionString: TEST_DB_URL, max: 8 })
    await _pool.query('SELECT 1')
    return _pool
}

export async function closeSharedPool(): Promise<void> {
    if (_pool) {
        await _pool.end()
        _pool = null
    }
}

export async function buildCluster(opts: BuildClusterOpts = {}): Promise<Cluster> {
    const teamId = opts.teamId ?? 1
    const pool = await getPool()

    // Single test DB holds both authoring (App, Revision) and runtime tables
    // (Session, User, SandboxInstance) — all Django-owned (the agent_platform
    // product DB). The production split happens at deploy time via two pool
    // URLs. reset() resets the agent_* tables between cases (see test-reset.ts).
    await reset({ databaseUrl: TEST_DB_URL })

    // Real S3 bundle store against SeaweedFS, per-cluster prefix. Same impl
    // prod runs against real S3 — no fs/in-memory variant. The bucket and
    // client come from the shared `buildTestBundleStore` helper which mirrors
    // `buildTestStore` for the memory store.
    const bundlePrefix = `agent_bundles_harness_${Math.random().toString(36).slice(2, 10)}`
    const { client: bundleClient, store: bundle } = buildTestBundleStore(bundlePrefix)
    const revisions = new PgRevisionStore(pool)
    const queue = new PgSessionQueue(pool)
    // Real Redis pub/sub with a per-cluster channel prefix so concurrent test
    // files don't deliver each other's events. Same impl prod runs; in-memory
    // bus has been removed. Teardown disconnects.
    const busChannelPrefix = `harness_${Math.random().toString(36).slice(2, 10)}`
    const bus: SessionEventBus & { connect: () => Promise<void>; disconnect: () => Promise<void> } =
        new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: busChannelPrefix })
    await bus.connect()
    const identities: IdentityStore = new PgIdentityStore(pool)
    // Real KafkaLogSink against the local broker. The tap captures wire
    // payloads as they're produced so tests can assert on event shape
    // without polling ClickHouse. Teardown disconnects.
    const collected: LogEntry[] = []
    const logSink = new KafkaLogSink({
        brokers: KAFKA_HOSTS,
        topic: 'log_entries',
        name: 'agent_tests',
        tap: (entry) => collected.push(entry),
    })
    await logSink.connect()
    const logs: CollectingLogSink = {
        get entries(): LogEntry[] {
            return collected
        },
        forSession(sessionId: string): LogEntry[] {
            return collected.filter((e) => e.session_id === sessionId)
        },
        clear(): void {
            collected.length = 0
        },
    }
    const sandboxes = new InProcessSandboxPool()
    const sandboxInstances = new PgSandboxInstanceStore(pool)
    const approvals = new PgApprovalStore(pool)
    const broker = new SecretBroker()
    // Real PG-backed credential broker — matches what prod runs. Mocking
    // this with an in-memory map would let test-only behavior diverge
    // from the real SQL path (per the harness CLAUDE.md "no fakes for
    // the persistence layer" rule).
    // Deterministic per-cluster key — encryption is the real path even
    // in tests so the encrypt/decrypt round-trip is exercised.
    // EncryptedFields expects a 32-byte UTF-8 string (same constraint
    // production uses; matches `pg-impls.test.ts`).
    const credentialBroker = new PgCredentialBroker(pool, {
        encryptionSaltKeys: HARNESS_ENCRYPTION_SALT_KEYS,
    })
    // Persistent linked-credential + OAuth link-state stores for identity linking.
    const identityCredentials = new PgIdentityCredentialStore(pool, {
        encryptionSaltKeys: HARNESS_ENCRYPTION_SALT_KEYS,
    })
    const identityLinks = new PgIdentityLinkStateStore(pool)
    // Real S3 (SeaweedFS) memory store with a per-cluster random prefix —
    // teardown wipes it. Failing here means SeaweedFS isn't up; fix the dev
    // stack rather than mocking around it.
    const memoryStorePrefix = newMemoryTestPrefix('agent_memory_harness')
    const { client: memoryStoreClient, store: memoryStore } = buildMemoryTestStore(memoryStorePrefix)
    // Tabular store shares the bucket + S3 client; the prefix scopes it under
    // the same harness root so teardown wipes both stores in one sweep.
    const tabularStore = new S3JsonlTabularStore({
        client: memoryStoreClient,
        bucket: TEST_S3_BUCKET,
        bucketPrefix: `${memoryStorePrefix}/tables`,
    })

    // Real RoutingAnalyticsSink with a stub per-team resolver + no-op client.
    // The tap captures the `$ai_*` wire shape as the runner emits it, so tests
    // assert per-team routing + event shapes without a real PostHog (the route
    // a team's events would take is `phc_team_<id>`).
    const analyticsCaptured: AnalyticsTapEntry[] = []
    const analyticsSink = new RoutingAnalyticsSink({
        resolveApiKey: async (teamId) => `phc_team_${teamId}`,
        createClient: () => ({ capture: () => undefined, shutdown: async () => undefined }),
        tap: (e) => analyticsCaptured.push(e),
        logger: { info: () => undefined, warn: () => undefined, error: () => undefined },
    })
    const analytics: CollectingAnalyticsSink = {
        get entries(): AnalyticsTapEntry[] {
            return analyticsCaptured
        },
        forSession(sessionId: string): AnalyticsTapEntry[] {
            return analyticsCaptured.filter((e) => e.event.session_id === sessionId)
        },
        clear(): void {
            analyticsCaptured.length = 0
        },
    }

    const model = opts.model ?? buildFauxModel(opts.initialScript ?? [])
    // resolveModel ignores spec.model and always returns the harness's Model —
    // tests don't exercise per-agent model selection (that's covered in
    // real-inference + dedicated tests).
    const resolveModelForHarness = (): typeof model => model

    // `@posthog/query` runs as the connected user against the Django
    // `/query/` endpoint via `ctx.http` (see `_posthog-api.ts`). The harness
    // has no live Django, so wrap the worker's http with an in-process echo
    // that returns the submitted HogQL string back as a single `query` column
    // — the same shape the old in-process client produced, so query cases keep
    // passing without a real PostHog. Non-query requests fall through.
    const harnessHttp = buildQueryEchoHttp(opts.http ?? new HttpClient())

    const worker = new Worker({
        queue,
        revisions,
        bundle,
        sandboxes,
        sandboxInstances,
        broker,
        credentialBroker,
        identityCredentials,
        identityLinks,
        identities,
        linkRedirectBaseUrl: 'http://callback.test',
        bus,
        logs: logSink,
        analytics: analyticsSink,
        resolveSecrets: opts.resolveSecrets ? async (s) => opts.resolveSecrets!(s.id) : async () => ({}),
        resolveModel: resolveModelForHarness,
        approvals,
        buildApprovalUrl: (requestId) => `/approvals?request=${requestId}`,
        memoryStore,
        tabularStore,
        mcpTransportFactory: opts.mcpTransportFactory,
        maxConcurrency: 1, // tests prefer serial for deterministic state checks
        // Real HttpClient with no proxy by default — tests that exercise
        // outbound HTTP hit real localhost servers (matches the wider harness
        // stance of real-everywhere except the model layer). Tests that
        // want to assert on outbound headers / short-circuit the network
        // override via `BuildClusterOpts.http`. Wrapped to echo `/query/`
        // (see `buildQueryEchoHttp`).
        http: harnessHttp,
        posthogApiBaseUrl: 'http://localhost:8010',
        webSearchProviders: opts.webSearchProviders,
    })

    // Real-flow Slack secret resolver: decrypts the agent's `encrypted_env`
    // via the same `EncryptedFields` key the credential broker uses, then
    // plucks the requested key. Tests populate `encrypted_env` on
    // `deployAgent` to wire a secret per agent — same path production uses.
    const encryption = new EncryptedFields(HARNESS_ENCRYPTION_SALT_KEYS)
    const slackSigningSecretResolver: SecretResolver =
        opts.slackSigningSecretResolver ?? new EncryptedEnvSecretResolver(encryption)

    const ingress = buildApp({
        revisions,
        queue,
        bus,
        routingMode: opts.routingMode ?? 'path',
        pathPrefix: '/agents',
        domainSuffix: opts.domainSuffix,
        slackSigningSecretResolver,
        authProvider: opts.authProvider,
        identities,
        credentialBroker,
        // Identity-linking callback route (`GET /link/:provider/callback`).
        identityCredentials,
        identityLinks,
        envEncryption: encryption,
        // Same `http` the worker uses, so tests asserting on outbound
        // slack.com calls from the ingress (ack_reaction, identity bridge)
        // can route them through a single recorder.
        http: opts.http,
        // Wire the JWT gate so preview-mode tests exercise the real claim
        // verification (audience, signature, app/rev binding). Without this the
        // resolver short-circuits and a non-live revision routes without a
        // token. Same key `mintInternalJwt` uses in the preview-mode fixtures.
        internalSigningKey: DEV_INTERNAL_SIGNING_KEY,
    })

    const janitor = buildJanitorApp({
        queue,
        approvals,
        revisions,
        bundles: bundle,
        sweep: { queue, approvals, stuckRunningThresholdMs: 60_000 },
        // Shared with the worker — same bucket, same prefix. Memory routes
        // (/memory/team/:t/agent/:a/...) read + write through this store and
        // the runner's `@posthog/memory-*` tools hit the same files.
        memoryStore,
    })

    return {
        pool,
        revisions,
        queue,
        bundle,
        bundlePrefix,
        bus,
        identities,
        sandboxInstances,
        logs,
        analytics,
        sandboxes,
        broker,
        credentialBroker,
        memoryStore,
        tabularStore,
        encryption,
        model,
        ingress,
        janitor,
        worker,
        signSlack(rawBody: string, secret: string): { ts: string; sig: string } {
            const ts = String(Math.floor(Date.now() / 1000))
            const mac = createHmac('sha256', secret).update(`v0:${ts}:${rawBody}`).digest('hex')
            return { ts, sig: `v0=${mac}` }
        },
        async slackPost(slug: string, action: string, body: object, secret: string): Promise<request.Response> {
            const raw = JSON.stringify(body)
            const ts = String(Math.floor(Date.now() / 1000))
            const mac = createHmac('sha256', secret).update(`v0:${ts}:${raw}`).digest('hex')
            return request(ingress)
                .post(`/agents/${slug}/slack/${action}`)
                .set('content-type', 'application/json')
                .set('x-slack-request-timestamp', ts)
                .set('x-slack-signature', `v0=${mac}`)
                .send(raw)
        },
        setScript(turns) {
            buildFauxModel(turns)
        },
        async deployAgent(input) {
            const tid = input.teamId ?? teamId
            // Fernet-encrypt the env map the same way Django would, so the
            // ingress's `SecretResolver` exercises real decrypt
            // → look-up at request time. Tests that don't pass `encrypted_env`
            // get null (matches an agent whose author never set any env).
            const encrypted_env = input.encrypted_env ? encryption.encrypt(JSON.stringify(input.encrypted_env)) : null
            const app = await revisions.createApplication({
                team_id: tid,
                slug: input.slug,
                name: input.name ?? input.slug,
                description: input.description ?? '',
            })
            const rawSpec: Record<string, unknown> = {
                // Default model is "faux/<name>"; tests can override via spec.models.
                models: { mode: 'manual', models: [{ model: 'faux/faux' }] },
                triggers: [
                    { type: 'chat', config: {} },
                    // Default to "*" for tests — individual cases override
                    // with explicit trusted_workspaces to exercise the gate.
                    { type: 'slack', config: { trusted_workspaces: '*' } },
                    { type: 'webhook', config: { path: '/webhook' } },
                    { type: 'mcp', config: {} },
                ],
                // Harness-only ergonomic: a top-level `auth` is distributed onto
                // every declarative trigger that doesn't set its own (below).
                // Production has NO spec-level auth — but letting tests say
                // `spec: { auth: { modes: [...] } }` keeps the common case a
                // one-liner. Default is public so auth-agnostic cases work
                // through `PUBLIC_ONLY_AUTH_PROVIDER`; cases exercising real
                // modes pass their own `auth` (and wire `fakeAuthProvider`).
                auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                ...input.spec,
            }
            const topAuth = rawSpec.auth
            delete rawSpec.auth
            if (topAuth && Array.isArray(rawSpec.triggers)) {
                for (const t of rawSpec.triggers as Array<Record<string, unknown>>) {
                    if ((t.type === 'webhook' || t.type === 'chat' || t.type === 'mcp') && t.auth === undefined) {
                        t.auth = topAuth
                    }
                }
            }
            const spec = AgentSpecSchema.parse(rawSpec)
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: `s3://${TEST_S3_BUCKET}/${bundlePrefix}/${app.id}/`,
                spec,
                encrypted_env,
            })
            for (const [p, content] of Object.entries(input.files ?? {})) {
                await bundle.write(rev.id, p, content)
            }
            if (!input.files?.['agent.md']) {
                await bundle.write(rev.id, 'agent.md', 'You are a test agent.')
            }
            const sha = await bundle.freeze(rev.id)
            await revisions.setRevisionState(rev.id, 'ready', sha)
            await revisions.setRevisionState(rev.id, 'live', sha)
            await revisions.setLiveRevision(app.id, rev.id)
            const refreshedApp = await revisions.getApplication(app.id)
            const refreshedRev = await revisions.getRevision(rev.id)
            return { application: refreshedApp!, revision: refreshedRev! }
        },
        async drain(o) {
            const maxIterations = o?.iterations ?? 50
            const maxEmpty = 3
            let empty = 0
            let i = 0
            while (i < maxIterations && empty < maxEmpty) {
                const session = await queue.claim(10)
                if (!session) {
                    empty++
                    await new Promise((r) => setTimeout(r, 20))
                    continue
                }
                empty = 0
                await worker.runOne(session)
                i++
            }
        },
        async teardown() {
            await wipeMemoryTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
            bundleClient.destroy()
            await wipeMemoryTestPrefix(memoryStoreClient, memoryStorePrefix).catch(() => undefined)
            memoryStoreClient.destroy()
            await bus.disconnect().catch(() => undefined)
            await logSink.disconnect().catch(() => undefined)
        },
    }
}
