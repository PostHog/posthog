import type { S3Client } from '@aws-sdk/client-s3'
import {
    type AssistantMessage,
    fauxAssistantMessage,
    fauxToolCall,
    type Model,
    registerFauxProvider,
    type ToolCall,
} from '@earendil-works/pi-ai'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import { z } from 'zod'

import {
    AgentSession,
    AgentSpecSchema,
    buildTestBundleStore,
    EMPTY_USAGE_TOTAL,
    HttpClient,
    InProcessSandboxPool,
    KafkaLogSink,
    newTestPrefix,
    PgApprovalStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
    S3BundleStore,
    SecretBroker,
    wipeTestPrefix,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'localhost:9092'

import type { McpTransportFactory } from '../loop/mcp-clients'
import { Worker, type WorkerDeps } from './worker'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
let pool: Pool
let bundlePrefix: string
let bundleClient: S3Client
let bundleStore: S3BundleStore

// The driver streams through pi-ai's registered faux provider (the same surface
// the e2e harness uses), so the worker is exercised via `resolveModel` returning
// a faux Model armed with a script — not an injected client.
let fauxHandle: ReturnType<typeof registerFauxProvider> | undefined
function fauxModel(script: Array<AssistantMessage | (() => AssistantMessage)>): Model<string> {
    if (!fauxHandle) {
        fauxHandle = registerFauxProvider({ api: 'faux', provider: 'faux', models: [{ id: 'faux' }] })
    }
    fauxHandle.setResponses(script.map((t) => (typeof t === 'function' ? () => t() : t)))
    return fauxHandle.getModel() as Model<string>
}
const endTurn = (text: string): AssistantMessage => fauxAssistantMessage(text, { stopReason: 'stop' })
const toolUseTurn = (calls: ToolCall[]): AssistantMessage => fauxAssistantMessage(calls, { stopReason: 'toolUse' })
const toolCall = (name: string, args: Record<string, unknown> = {}): ToolCall => fauxToolCall(name, args)

// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'
const workerTestBus = new RedisSessionEventBus({
    url: REDIS_URL,
    channelPrefix: `worker_test_${Math.random().toString(36).slice(2, 10)}`,
})

const workerTestLogs = new KafkaLogSink({ brokers: KAFKA_HOSTS, topic: 'log_entries', name: 'worker_test' })

describe('Worker', () => {
    beforeAll(async () => {
        await workerTestBus.connect()
        await workerTestLogs.connect()
        pool = new Pool({ connectionString: TEST_DB_URL })
    })

    afterAll(async () => {
        await workerTestBus.disconnect()
        await workerTestLogs.disconnect()
        await pool.end()
    })

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
        bundlePrefix = newTestPrefix('agent_bundles_worker_test')
        const built = buildTestBundleStore(bundlePrefix)
        bundleClient = built.client
        bundleStore = built.store
    })

    afterEach(async () => {
        if (bundleClient) {
            await wipeTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
            bundleClient.destroy()
        }
    })

    it('refuses to construct without an approval store (fail-closed)', () => {
        // The constructor must crash rather than run a worker that silently
        // skips every requires_approval gate.
        expect(() => new Worker({} as unknown as WorkerDeps)).toThrow(/approvals is required/)
    })

    it('claims a session, runs it, marks it completed', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'faux/test' }),
        })
        await bundle.write(rev.id, 'agent.md', 'you are a bot')

        const sessionId = randomUUID()
        const session: AgentSession = {
            id: sessionId,
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hello', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([endTurn('hi back')]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get(sessionId)
        expect(after!.state).toBe('completed')
    })

    it('session with custom tool acquires + releases the sandbox', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)
        const COMPILED = `
            module.exports = {
                id: "noop",
                actions: { default: () => ({ ok: true }) },
            }
        `

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'faux/test',
                tools: [{ kind: 'custom', id: 'noop', path: 'tools/noop/' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')
        await bundle.write(rev.id, 'tools/noop/compiled.js', COMPILED)
        await bundle.write(rev.id, 'tools/noop/schema.json', JSON.stringify({ description: 'noop' }))

        const sessionId = randomUUID()
        const session: AgentSession = {
            id: sessionId,
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const sandboxes = new InProcessSandboxPool()
        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes,
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({ ACME_KEY: 'topsecret' }),
            resolveModel: () => fauxModel([toolUseTurn([toolCall('noop', {})]), endTurn('done')]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get(sessionId)
        expect(after!.state).toBe('completed')
    })

    it('opens spec.mcps[] at session start, dispatches a remote tool, closes on finish', async () => {
        // End-to-end shape: spec declares an MCP, the worker calls
        // `openMcpClients` via the injected transport factory (paired with an
        // in-process `McpServer`), the faux model invokes the prefixed tool,
        // the result lands in `session.conversation`, and the transport pair
        // is closed in the worker's `finally`.
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'faux/test',
                mcps: [{ kind: 'agent', default_tool_approval: 'allow', id: 'echo', url: 'https://example.com/echo' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'you are a bot')

        const session: AgentSession = {
            id: randomUUID(),
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'say hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        // Track whether the server-side transport got a close call — proves
        // the worker's `finally` ran. Each connect builds a fresh pair so
        // multiple sessions in the same suite stay isolated.
        const serverClosed = { count: 0 }
        const echoCalls: Array<{ msg: string }> = []
        const factory: McpTransportFactory = (): Transport => {
            const server = new McpServer({ name: 'echo-mcp', version: '1.0.0' })
            server.registerTool(
                'echo',
                {
                    title: 'Echo',
                    description: 'Echo input back.',
                    inputSchema: { msg: z.string() },
                },
                async ({ msg }) => {
                    echoCalls.push({ msg })
                    return { content: [{ type: 'text' as const, text: msg }] }
                }
            )
            const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
            const originalClose = serverTransport.close?.bind(serverTransport)
            serverTransport.close = async () => {
                serverClosed.count++
                await originalClose?.()
            }
            void server.server.connect(serverTransport)
            return clientTransport
        }

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({}),
            resolveModel: () =>
                fauxModel([toolUseTurn([toolCall('echo__echo', { msg: 'hi there' })]), endTurn('done')]),
            mcpTransportFactory: factory,
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get(session.id)
        expect(after!.state).toBe('completed')
        expect(echoCalls).toEqual([{ msg: 'hi there' }])
        // The transport pair is closed via the worker's `finally`. The
        // batched closer runs `client.close()`, which terminates the
        // paired server transport — we assert the count is ≥1 rather
        // than == to tolerate the SDK calling close again on its own
        // teardown path.
        expect(serverClosed.count).toBeGreaterThanOrEqual(1)
    })

    it('shutdown signal re-queues an in-flight session as queued for handoff', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)

        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({
                model: 'faux/test',
                tools: [{ kind: 'native', id: '@posthog/query' }],
            }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')

        const session: AgentSession = {
            id: randomUUID(),
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({}),
            resolveModel: () =>
                fauxModel([
                    (() => {
                        // Signal shutdown after the first turn so the next iteration sees it.
                        queueMicrotask(() => void worker.stop())
                        return toolUseTurn([toolCall('@posthog/query', { query: 'x' })])
                    }) as () => AssistantMessage,
                    endTurn('never reaches here'),
                ]),
        })

        await worker.loop({ iterations: 1, claimTimeoutMs: 10 })
        const after = await queue.get(session.id)
        // After shutdown mid-loop, session is re-queued for sibling pickup.
        expect(after!.state).toBe('queued')
        // Conversation persists across the handoff.
        expect(after!.conversation.length).toBeGreaterThan(1)
    })

    // Regression: a malformed revision.spec used to throw a ZodError out of
    // PgRevisionStore.getRevision(), which propagated through runOne (then
    // outside the try/catch) and crashed the worker loop. The boundary now
    // sits at the top of runOne, so the bad session is marked failed and a
    // sibling can keep being processed.
    it('runOne catches errors from revisions.getRevision and fails the session', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
        const session: AgentSession = {
            id: randomUUID(),
            application_id: app.id,
            revision_id: '00000000-0000-0000-0000-deadbeefdead',
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        // Stub getRevision to throw the kind of ZodError PgRevisionStore would
        // raise on a malformed spec column.
        const throwingRevisions = {
            ...revisions,
            getRevision: async () => {
                throw new Error('AgentSpecSchema parse error')
            },
        } as unknown as typeof revisions

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions: throwingRevisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([endTurn('would never run')]),
        })

        // The loop should not throw — runOne owns the boundary.
        await expect(worker.loop({ iterations: 1, claimTimeoutMs: 10 })).resolves.toBeUndefined()
        const after = await queue.get(session.id)
        expect(after!.state).toBe('failed')
    })

    // The pre-flight inside `runOne` (revision load, secrets, sandbox
    // acquire, custom-tool bundle reads) sits under one try/catch.
    // Each failure mode below would crash the worker loop pre-fix; the
    // boundary now fails just the one session.
    type FailureCase = {
        name: string
        withCustomTool: boolean
        overrides: (failingPool: InProcessSandboxPool) => Partial<{
            resolveSecrets: () => Promise<Record<string, string>>
            sandboxes: InProcessSandboxPool
            resolveModel: (specModel: string) => never
        }>
    }
    const PREFLIGHT_CASES: FailureCase[] = [
        {
            name: 'resolveSecrets throws',
            withCustomTool: false,
            overrides: () => ({
                resolveSecrets: async () => {
                    throw new Error('decryption failed')
                },
            }),
        },
        {
            name: 'sandboxes.acquireForSession throws',
            withCustomTool: true,
            overrides: (failingPool) => ({ sandboxes: failingPool }),
        },
        {
            // Regression: pi-ai's `getModel(provider, modelId)` returns
            // undefined for an unknown id. Before the fix in pi-client.ts the
            // undefined Model flowed into runSession and crashed
            // `errorContext()` on `deps.model.id` with the cryptic
            // "Cannot read properties of undefined (reading 'id')". Now
            // `resolveModel` throws an explicit `unknown_model_id: …` error
            // pre-flight and the session is marked failed.
            name: 'resolveModel returns undefined (unknown model id)',
            withCustomTool: false,
            overrides: () => ({
                resolveModel: () => {
                    throw new Error(
                        'unknown_model_id: spec.model="anthropic/claude-sonnet-4-7" — pi-ai has no model "claude-sonnet-4-7" registered for provider "anthropic". Check the pi-ai models registry or upgrade @earendil-works/pi-ai.'
                    )
                },
            }),
        },
    ]

    it.each(PREFLIGHT_CASES)(
        'runOne fails the session (loop survives) when $name',
        async ({ withCustomTool, overrides }) => {
            const revisions = new PgRevisionStore(pool)
            const bundle = bundleStore
            const queue = new PgSessionQueue(pool)
            const app = await revisions.createApplication({ team_id: 1, slug: 'x', name: 'X', description: '' })
            const COMPILED = `module.exports = { id: "noop", actions: { default: () => ({}) } }`
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({
                    model: 'faux/test',
                    tools: withCustomTool ? [{ kind: 'custom', id: 'noop', path: 'tools/noop/' }] : [],
                }),
            })
            await bundle.write(rev.id, 'agent.md', 'x')
            if (withCustomTool) {
                await bundle.write(rev.id, 'tools/noop/compiled.js', COMPILED)
                await bundle.write(rev.id, 'tools/noop/schema.json', '{}')
            }
            const session: AgentSession = {
                id: randomUUID(),
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                idempotency_key: null,
                trigger_metadata: null,
                state: 'queued',
                conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                acl: [],
                pending_elevation_requests: [],
                usage_total: { ...EMPTY_USAGE_TOTAL },
                created_at: '2026-05-27',
                updated_at: '2026-05-27',
            }
            await queue.enqueue(session)

            // A pool that always rejects acquireForSession — only matters for
            // the sandbox-failure case but cheap to construct unconditionally.
            const failingPool = new InProcessSandboxPool()
            failingPool.acquireForSession = async () => {
                throw new Error('sandbox pool exhausted')
            }

            const worker = new Worker({
                http: new HttpClient(),
                posthogApiBaseUrl: 'http://localhost:8010',
                queue,
                revisions,
                bundle,
                sandboxes: new InProcessSandboxPool(),
                broker: new SecretBroker(),
                bus: workerTestBus,
                logs: workerTestLogs,
                approvals: new PgApprovalStore(pool),
                resolveSecrets: async () => ({}),
                resolveModel: () => fauxModel([endTurn('would never run')]),
                ...overrides(failingPool),
            })

            await expect(worker.loop({ iterations: 1, claimTimeoutMs: 10 })).resolves.toBeUndefined()
            const after = await queue.get(session.id)
            expect(after!.state).toBe('failed')

            // Pre-runSession failures must surface a synthetic assistant
            // message in the conversation so the user sees *something* in
            // the transcript instead of their lone user turn followed by
            // silence. (The driver's in-loop failure path already covers
            // this for failures inside runSession; this regression test pins
            // the same behaviour for failures BEFORE runSession ever runs.)
            // The text is sanitized via FailureNotifier's `userFacingMessage`
            // (raw infra detail stays in log_entries / errorMessage) — we
            // assert it's a non-empty user-readable sentence, not the raw
            // exception string.
            const last = after!.conversation[after!.conversation.length - 1] as
                | {
                      role: string
                      content: Array<{ type: string; text?: string }>
                      stopReason?: string
                      errorMessage?: string
                  }
                | undefined
            expect(last?.role).toBe('assistant')
            expect(last?.stopReason).toBe('error')
            const text = last?.content?.[0]?.text ?? ''
            expect(text.length).toBeGreaterThan(0)
            expect(text).not.toMatch(/docker|kafka|redis|stack|streamable http/i)
            // Raw reason is preserved on `errorMessage` for owner-facing debug.
            expect(last?.errorMessage).toBeTruthy()
        }
    )

    it('runOne publishes a `failed` lifecycle event + writes a log entry on pre-runSession failure', async () => {
        // Asserts the bus + log surfaces directly. Uses stub impls instead of
        // the real Redis/Kafka the rest of this file shares — point of the
        // test is to prove the catch reaches both, not the transport details.
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)
        const app = await revisions.createApplication({
            team_id: 1,
            slug: 'preflight-fanout',
            name: 'X',
            description: '',
        })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'faux/test', tools: [] }),
        })
        await bundle.write(rev.id, 'agent.md', 'x')
        const session: AgentSession = {
            id: randomUUID(),
            application_id: app.id,
            revision_id: rev.id,
            team_id: 1,
            external_key: null,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            acl: [],
            pending_elevation_requests: [],
            usage_total: { ...EMPTY_USAGE_TOTAL },
            created_at: '2026-05-27',
            updated_at: '2026-05-27',
        }
        await queue.enqueue(session)

        const busPublishes: Array<{ kind: string; data: Record<string, unknown> }> = []
        const stubBus = {
            publish: async (e: { kind: string; data: Record<string, unknown> }) => {
                busPublishes.push({ kind: e.kind, data: e.data })
            },
            subscribe: () => () => undefined,
        }
        const logWrites: Array<{ event: string; level: string; data: Record<string, unknown> }> = []
        const stubLogs = {
            connect: async () => undefined,
            disconnect: async () => undefined,
            write: async (entries: Array<{ event: string; level: string; data: Record<string, unknown> }>) => {
                for (const entry of entries) {
                    logWrites.push({ event: entry.event, level: entry.level, data: entry.data })
                }
            },
        }

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: stubBus as unknown as RedisSessionEventBus,
            logs: stubLogs as unknown as KafkaLogSink,
            approvals: new PgApprovalStore(pool),
            // Pick a deterministic pre-runSession failure — `resolveSecrets`
            // throws before the driver runs.
            resolveSecrets: async () => {
                throw new Error('Streamable HTTP error: Error POSTing to endpoint: Endpoint not found.')
            },
            resolveModel: () => fauxModel([endTurn('would never run')]),
        })

        await expect(worker.loop({ iterations: 1, claimTimeoutMs: 10 })).resolves.toBeUndefined()

        // The failure landed on all three surfaces:
        //   - DB row state = failed (pinned by the parameterized test above)
        //   - Bus `failed` event with an EMPTY payload — raw reason +
        //     source must never reach the SSE wire because the bus fans
        //     out to every chat client connected to the session
        //   - Log entry with event: failed + level: error + full reason +
        //     source: pre_run_session, for the agent owner to debug via
        //     the session-detail page (which reads log_entries)
        const failedEvent = busPublishes.find((e) => e.kind === 'failed')
        expect(failedEvent).not.toBeUndefined()
        expect(failedEvent?.data).toEqual({})
        const failedLog = logWrites.find((e) => e.event === 'failed')
        expect(failedLog?.level).toBe('error')
        expect(failedLog?.data).toMatchObject({
            reason: expect.stringContaining('Endpoint not found'),
            source: 'pre_run_session',
        })
    })

    it('main loop swallows transient claim() errors instead of crashing', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)

        let claimCalls = 0
        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([]),
        })
        // First claim throws (transient PG error). Second time, signal a clean
        // shutdown so the loop exits — confirming the worker survived the
        // throw and is still spinning afterward.
        queue.claim = async () => {
            claimCalls++
            if (claimCalls === 1) {
                throw new Error('transient PG error')
            }
            await worker.stop()
            return null
        }

        await expect(worker.loop({ iterations: 5, claimTimeoutMs: 5 })).resolves.toBeUndefined()
        expect(claimCalls).toBeGreaterThanOrEqual(2)
    })

    it('backs off exponentially on consecutive claim() failures and resets after a success', async () => {
        const revisions = new PgRevisionStore(pool)
        const bundle = bundleStore
        const queue = new PgSessionQueue(pool)

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            bus: workerTestBus,
            logs: workerTestLogs,
            approvals: new PgApprovalStore(pool),
            resolveSecrets: async () => ({}),
            resolveModel: () => fauxModel([]),
        })

        // Record the backoff delays without actually waiting. The private
        // `sleep` is the single choke point the loop awaits between retries.
        const delays: number[] = []
        ;(worker as unknown as { sleep: (ms: number) => Promise<void> }).sleep = async (ms: number) => {
            delays.push(ms)
        }

        // Four straight failures, then a clean (null) claim that should reset
        // the counter, then one more failure that must start from the base
        // window again — proving the reset.
        let claimCalls = 0
        queue.claim = async () => {
            claimCalls++
            if (claimCalls <= 4) {
                throw new Error('transient PG error')
            }
            if (claimCalls === 5) {
                return null // success path — resets consecutiveClaimFailures
            }
            await worker.stop()
            throw new Error('one more transient PG error after the reset')
        }

        // base/max kept well apart so the first failures never hit the cap and
        // the equal-jitter floor stays strictly growing across them.
        await expect(
            worker.loop({ iterations: 50, claimTimeoutMs: 5, claimBackoffBaseMs: 100, claimBackoffMaxMs: 100_000 })
        ).resolves.toBeUndefined()

        // 4 failures + 1 post-reset failure = 5 backoff sleeps.
        expect(delays.length).toBe(5)
        // Equal jitter → delay_n ∈ [base·2^(n-1)/2, base·2^(n-1)]; consecutive
        // windows abut, so the first four are non-decreasing.
        const firstFour = delays.slice(0, 4)
        for (let i = 1; i < firstFour.length; i++) {
            expect(firstFour[i]).toBeGreaterThanOrEqual(firstFour[i - 1])
        }
        // Fourth failure window is [400, 800]; the fifth sleep is the
        // post-reset failure, back in the base window [50, 100] — strictly
        // smaller, which is only possible if the success reset the counter.
        expect(delays[4]).toBeLessThan(delays[3])
        expect(delays[4]).toBeLessThanOrEqual(100)
    })
})
