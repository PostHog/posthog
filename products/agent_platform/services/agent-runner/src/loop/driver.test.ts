import type { S3Client } from '@aws-sdk/client-s3'
import {
    type AssistantMessage,
    type AssistantMessageEvent,
    createAssistantMessageEventStream,
    fauxAssistantMessage,
    fauxToolCall,
    type Model,
    registerFauxProvider,
    streamSimple,
    type ToolCall,
} from '@earendil-works/pi-ai'
import { Pool } from 'pg'

import {
    type AnalyticsEvent,
    type AnalyticsGenerationEvent,
    type AnalyticsSink,
    AgentRevision,
    type ApprovalRequest,
    type ApprovalStore,
    AgentSession,
    AgentSpecSchema,
    buildTestBundleStore,
    EMPTY_USAGE_TOTAL,
    HttpClient,
    KafkaLogSink,
    McpRef,
    newTestPrefix,
    PgApprovalStore,
    PgSessionQueue,
    RedisSessionEventBus,
    S3BundleStore,
    SessionPrincipal,
    wipeTestPrefix,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'localhost:9092'

import { buildApprovalDecidedMarker } from '@posthog/agent-shared'

import { runSession } from './driver'
import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'

const FAUX_MODEL_ID = 'faux/test'
// Realistic UUID — PG's `uuid` columns (approvals.session_id, etc.) reject
// arbitrary strings, so the previous `'sess1'` literal broke any test that
// touched a real `PgApprovalStore`.
const TEST_SESSION_ID = '00000000-0000-4000-8000-00000000fe01'
const TEST_APP_ID = '00000000-0000-4000-8000-00000000aa01'
const TEST_REV_ID = '00000000-0000-4000-8000-00000000aa02'

let fauxHandle: ReturnType<typeof registerFauxProvider> | undefined
function fauxModel(script: Array<AssistantMessage | (() => AssistantMessage)>): Model<string> {
    if (!fauxHandle) {
        fauxHandle = registerFauxProvider({ api: 'faux', provider: 'faux', models: [{ id: 'faux' }] })
    }
    fauxHandle.setResponses(script.map((t) => (typeof t === 'function' ? () => t() : t)))
    return fauxHandle.getModel() as Model<string>
}
const stop = (text: string): AssistantMessage => fauxAssistantMessage(text, { stopReason: 'stop' })
const toolUse = (calls: ToolCall[]): AssistantMessage => fauxAssistantMessage(calls, { stopReason: 'toolUse' })
const call = (name: string, args: Record<string, unknown> = {}): ToolCall => fauxToolCall(name, args)
const lengthCapped = (): AssistantMessage => fauxAssistantMessage('(cut)', { stopReason: 'length' })
const errored = (msg: string): AssistantMessage => fauxAssistantMessage('', { stopReason: 'error', errorMessage: msg })

function makeRev(spec: Partial<Parameters<typeof AgentSpecSchema.parse>[0]> = {}): AgentRevision {
    return {
        id: TEST_REV_ID,
        application_id: TEST_APP_ID,
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-05-29',
        state: 'live',
        bundle_uri: 's3://x/',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: FAUX_MODEL_ID, ...spec }),
        encrypted_env: null,
    }
}

function makeSession(over: Partial<AgentSession> = {}): AgentSession {
    return {
        id: TEST_SESSION_ID,
        application_id: TEST_APP_ID,
        revision_id: TEST_REV_ID,
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: null,
        conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
        pending_inputs: [],
        retry_count: 0,
        acl: [],
        pending_elevation_requests: [],
        usage_total: { ...EMPTY_USAGE_TOTAL },
        created_at: '2026-05-29',
        updated_at: '2026-05-29',
        ...over,
    }
}

// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'
const driverTestBus = new RedisSessionEventBus({
    url: REDIS_URL,
    channelPrefix: `driver_test_${Math.random().toString(36).slice(2, 10)}`,
})

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
let pool: Pool
let bundlePrefix: string
let bundleClient: S3Client
let bundleStore: S3BundleStore
const driverTestLogs = new KafkaLogSink({ brokers: KAFKA_HOSTS, topic: 'log_entries', name: 'driver_test' })

beforeAll(async () => {
    await driverTestBus.connect()
    await driverTestLogs.connect()
    pool = new Pool({ connectionString: TEST_DB_URL })
})

afterAll(async () => {
    await driverTestBus.disconnect()
    await driverTestLogs.disconnect()
    await pool.end()
})

beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
    bundlePrefix = newTestPrefix('agent_bundles_driver_test')
    const built = buildTestBundleStore(bundlePrefix)
    bundleClient = built.client
    bundleStore = built.store
})

afterEach(async () => {
    await wipeTestPrefix(bundleClient, bundlePrefix).catch(() => undefined)
    bundleClient.destroy()
})

/**
 * Seed PG with an `agent_session` row for the session. Required when the
 * test wires `PgApprovalStore` because `agent_tool_approval_request.session_id`
 * has a FK to `agent_session(id)`. Tests that don't touch approvals can skip
 * this — the in-memory session struct passed to `runSession` is enough.
 */
async function seedSessionRow(session: AgentSession): Promise<void> {
    const queue = new PgSessionQueue(pool)
    await queue.enqueue(session)
}

async function run(
    rev: AgentRevision,
    session: AgentSession,
    over: Record<string, unknown> = {}
): ReturnType<typeof runSession> {
    const bundle = bundleStore
    await bundle.write(rev.id, 'agent.md', 'you are a bot')
    // Seed PG whenever the test needs the session to exist there: the
    // approval store requires the FK target, AND the runner now drains
    // pending_inputs through the PG queue rather than the in-memory copy
    // — so any test that seeds `pending_inputs` upfront needs the row
    // to be persisted too.
    if (over.approvals || session.pending_inputs.length > 0) {
        await seedSessionRow(session)
    }
    return runSession(rev, session, {
        models: [{ model: fauxModel((over.script as AssistantMessage[]) ?? [stop('ok')]) }],
        bundle,
        sandbox: null,
        secrets: {},
        inputs: new PgSessionQueue(pool),
        bus: driverTestBus,
        logs: driverTestLogs,
        // approvals is mandatory — runSession refuses to run without it.
        // Tests exercising the gate override via `over`; the rest just need a
        // real store wired so gating stays on (no ungated fast path).
        approvals: new PgApprovalStore(pool),
        http: new HttpClient(),
        posthogApiBaseUrl: 'http://localhost:8010',
        ...over,
    })
}

describe('driver runSession', () => {
    // These tests use `@posthog/query` purely as a generic native tool. The
    // sessions carry no `posthog` principal, so the tool fails closed
    // (`posthog_user_context_required`) before any HTTP call — the loop renders
    // that as a tool result, which is all the dispatch assertions below need.
    // The approval-gating tests assert it never even reaches dispatch.

    describe('approval gating is fail-closed', () => {
        it('refuses to run without an approval store wired', async () => {
            // Overriding approvals to undefined must crash, not silently run
            // every requires_approval tool ungated.
            await expect(run(makeRev(), makeSession(), { approvals: undefined })).rejects.toThrow(
                /approvals is required/
            )
        })
    })

    describe('RunOutcome derivation', () => {
        it('completes on stopReason=stop (one turn)', async () => {
            const session = makeSession()
            const out = await run(makeRev(), session, { script: [stop('hi back')] })
            expect(out).toEqual({ state: 'completed', turns: 1 })
            expect(session.conversation).toHaveLength(2)
        })

        it('dispatches a native tool then completes (two turns)', async () => {
            const session = makeSession()
            const out = await run(makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] }), session, {
                script: [toolUse([call('@posthog/query', { query: 'x' })]), stop('done')],
            })
            expect(out).toEqual({ state: 'completed', turns: 2 })
            // user + assistant(toolCall) + toolResult + assistant(final)
            expect(session.conversation).toHaveLength(4)
            const tr = session.conversation[2] as { role: string; toolName: string }
            expect(tr.role).toBe('toolResult')
            expect(tr.toolName).toBe('@posthog/query')
        })

        it('closes on meta-end-session with summary', async () => {
            const out = await run(makeRev(), makeSession(), {
                script: [toolUse([call('@posthog/meta-end-session', { summary: 'all done' })])],
            })
            expect(out.state).toBe('closed')
            expect(out.state === 'closed' && out.summary).toBe('all done')
        })

        it('fails with output_truncated on stopReason=length', async () => {
            const out = await run(makeRev(), makeSession(), { script: [lengthCapped()] })
            expect(out).toEqual({ state: 'failed', reason: 'output_truncated', turns: 1 })
        })

        it('fails with the model error reason on stopReason=error', async () => {
            const out = await run(makeRev(), makeSession(), { script: [errored('rate_limit')] })
            expect(out.state).toBe('failed')
            expect(out.state === 'failed' && out.reason).toBe('rate_limit')
        })

        it('suspends (turns=0) when the shutdown signal is already aborted', async () => {
            const ac = new AbortController()
            ac.abort()
            const out = await run(makeRev(), makeSession(), { script: [stop('never')], shutdownSignal: ac.signal })
            expect(out).toEqual({ state: 'suspended', reason: 'shutdown', turns: 0 })
        })

        it('drains pending_inputs into the conversation', async () => {
            const session = makeSession({
                pending_inputs: [{ role: 'user', content: 'follow up', timestamp: Date.now() }],
            })
            const out = await run(makeRev(), session, { script: [stop('ok')] })
            expect(out.state).toBe('completed')
            // pending_inputs lives in PG now (the runner drains via
            // `inputs.drainPendingInputs`); the in-memory copy is stale.
            const refreshed = await new PgSessionQueue(pool).get(session.id)
            expect(refreshed?.pending_inputs).toHaveLength(0)
            // original user + drained user + assistant
            expect(session.conversation).toHaveLength(3)
        })
    })

    describe('max_turns boundary', () => {
        // The agent gets exactly max_turns turns; it only fails if it still
        // wants to continue after the last one. Finishing ON the last turn
        // completes (a deliberate change from the old unconditional failure).
        it('fails when the agent still wants tools at the cap', async () => {
            const out = await run(
                makeRev({
                    tools: [{ kind: 'native', id: '@posthog/query' }],
                    limits: { max_turns: 2, max_tool_calls: 10, max_wall_seconds: 60 },
                }),
                makeSession(),
                {
                    script: [
                        toolUse([call('@posthog/query', { query: 'x' })]),
                        toolUse([call('@posthog/query', { query: 'y' })]),
                        stop('unreached'),
                    ],
                }
            )
            expect(out).toEqual({ state: 'failed', reason: 'max_turns_exceeded', turns: 2 })
        })

        it('completes when the agent finishes exactly on the last allowed turn', async () => {
            const out = await run(
                makeRev({
                    tools: [{ kind: 'native', id: '@posthog/query' }],
                    limits: { max_turns: 2, max_tool_calls: 10, max_wall_seconds: 60 },
                }),
                makeSession(),
                { script: [toolUse([call('@posthog/query', { query: 'x' })]), stop('done')] }
            )
            expect(out).toEqual({ state: 'completed', turns: 2 })
        })
    })

    describe('approval marker safety in getSteeringMessages', () => {
        // A fake store whose row belongs to a DIFFERENT session.
        function storeWithRow(row: Partial<ApprovalRequest>): ApprovalStore {
            return {
                get: async () =>
                    ({ id: 'req1', state: 'approving', tool_name: '@posthog/query', ...row }) as ApprovalRequest,
            } as unknown as ApprovalStore
        }

        // A dispatched `@posthog/query` always lands a toolResult in the
        // conversation (a success result, or — with no posthog principal — an
        // error result). Its ABSENCE proves the gated tool never ran.
        const ranQuery = (s: AgentSession | null): boolean =>
            (s?.conversation ?? []).some((m) => (m as { toolName?: string }).toolName === '@posthog/query')

        it('drops a marker whose approval row belongs to another session (no hijack)', async () => {
            const session = makeSession({
                pending_inputs: [{ role: 'user', content: buildApprovalDecidedMarker('req1'), timestamp: Date.now() }],
            })
            const out = await run(
                makeRev({ tools: [{ kind: 'native', id: '@posthog/query', requires_approval: true } as never] }),
                session,
                {
                    script: [stop('ok')],
                    approvals: storeWithRow({ session_id: 'someone-elses-session' }),
                }
            )
            expect(out.state).toBe('completed')
            // Marker consumed (dropped), not left dangling — verified
            // against PG since the runner no longer mutates the
            // in-memory session.pending_inputs.
            const refreshed = await new PgSessionQueue(pool).get(session.id)
            expect(refreshed?.pending_inputs).toHaveLength(0)
            // The cross-session approved tool must NOT have run.
            expect(ranQuery(refreshed)).toBe(false)
        })

        it('drops a marker whose row is not in the approving state', async () => {
            const session = makeSession({
                pending_inputs: [{ role: 'user', content: buildApprovalDecidedMarker('req1'), timestamp: Date.now() }],
            })
            const out = await run(
                makeRev({ tools: [{ kind: 'native', id: '@posthog/query', requires_approval: true } as never] }),
                session,
                {
                    script: [stop('ok')],
                    approvals: storeWithRow({ session_id: TEST_SESSION_ID, state: 'rejected' }),
                }
            )
            expect(out.state).toBe('completed')
            const refreshed = await new PgSessionQueue(pool).get(session.id)
            expect(refreshed?.pending_inputs).toHaveLength(0)
            expect(ranQuery(refreshed)).toBe(false)
        })
    })

    /**
     * MCP-sourced tools materialise at session start from `client.listTools()`,
     * so they never appear in `spec.tools[]` and the native/custom approval
     * lookup misses them. PR 7 added a fallback that decomposes
     * `<prefix>__<remoteName>` against `spec.mcps[].tools[]` — these tests pin
     * the wrap path for the MCP variant + the `principal` gate the concierge
     * relies on (which always queues — there is no fast-path).
     */
    describe('MCP tool approval gating', () => {
        // Minimal `OpenedMcp` stub — same shape as `build-agent-tools.test.ts`'s
        // helper but trimmed to what these cases need. Tracks `callTool`
        // invocations so we can assert the gated path didn't reach the
        // remote.
        function makeFakeMcp(
            prefix: string,
            ref: McpRef,
            tools: Record<string, { description: string; result: unknown }>
        ): OpenedMcp & { calls: Array<{ name: string; args: Record<string, unknown> }> } {
            const calls: Array<{ name: string; args: Record<string, unknown> }> = []
            return {
                prefix,
                ref,
                listTools: async (): Promise<RemoteMcpTool[]> =>
                    Object.entries(tools).map(([name, t]) => ({
                        name,
                        description: t.description,
                        inputSchema: { type: 'object' },
                    })),
                callTool: async (name, args) => {
                    calls.push({ name, args })
                    const result = tools[name]?.result ?? null
                    return {
                        content: [{ type: 'text' as const, text: JSON.stringify(result) }],
                        structuredContent: result as Record<string, unknown>,
                    }
                },
                close: async () => undefined,
                calls,
            } as OpenedMcp & { calls: typeof calls }
        }

        // Route through `AgentSpecSchema.parse` so the approval-policy
        // defaults (`type`, `allow_edit`, `ttl_ms`) get materialised — the
        // runner reads the strict shape, not the zod input form.
        const POSTHOG_REF: McpRef = AgentSpecSchema.parse({
            model: FAUX_MODEL_ID,
            mcps: [
                {
                    kind: 'agent',
                    default_tool_approval: 'deny',
                    id: 'posthog',
                    url: 'https://app.posthog.com/api/mcp',
                    secrets: [],
                    tools: [
                        { name: 'agent-applications-list', level: 'allow' },
                        {
                            name: 'agent-applications-revisions-promote-create',
                            level: 'approve',
                            approval_policy: { type: 'principal', ttl_ms: 900_000 },
                        },
                    ],
                },
            ],
        }).mcps[0]

        const principalAlice: SessionPrincipal = {
            kind: 'posthog',
            user_id: 'alice',
            team_id: 1,
        }

        it('queues an approval row when the model calls a gated MCP tool', async () => {
            // Concierge-shape: the model invokes promote-create; the
            // dispatcher's MCP lookup finds `level: 'approve'` on the
            // matching tools[] entry; the wrap queues instead of running.
            const mcp = makeFakeMcp('posthog', POSTHOG_REF, {
                'agent-applications-revisions-promote-create': { description: 'd', result: { promoted: true } },
            })
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({
                principal: principalAlice,
                conversation: [{ role: 'user', content: 'promote it', sender: principalAlice, timestamp: Date.now() }],
            })
            const out = await run(makeRev({ mcps: [POSTHOG_REF as never] }), session, {
                script: [
                    toolUse([
                        call('posthog__agent-applications-revisions-promote-create', {
                            application_id: 'app',
                        }),
                    ]),
                    stop('queued'),
                ],
                approvals,
                mcpClients: [mcp],
                // No `isAskerInApproverScope` wired → no fast-path → the
                // gated call must take the queue path.
            })
            expect(out.state).toBe('completed')
            // Remote tool was NEVER called.
            expect(mcp.calls).toEqual([])
            // Exactly one approval row queued for this session.
            const rows = await approvals.listBySession(TEST_SESSION_ID)
            expect(rows).toHaveLength(1)
            expect(rows[0].tool_name).toBe('posthog__agent-applications-revisions-promote-create')
            expect(rows[0].state).toBe('queued')
        })

        it('does NOT queue when the matching tools[] entry is allow-level (inclusion only)', async () => {
            // `agent-applications-list` is in tools[] with `level: 'allow'` —
            // exposed but not gated. The dispatcher's MCP lookup returns a
            // non-gating level, the native lookup doesn't match either, so the
            // tool dispatches directly. Sibling case below pins iteration order
            // so this isn't a false-positive on accidental short-circuit.
            const mcp = makeFakeMcp('posthog', POSTHOG_REF, {
                'agent-applications-list': { description: 'd', result: { results: [] } },
            })
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({ principal: principalAlice })
            const out = await run(makeRev({ mcps: [POSTHOG_REF as never] }), session, {
                script: [toolUse([call('posthog__agent-applications-list', {})]), stop('listed')],
                approvals,
                mcpClients: [mcp],
            })
            expect(out.state).toBe('completed')
            // Remote was hit normally — no approval interception.
            expect(mcp.calls).toEqual([{ name: 'agent-applications-list', args: {} }])
            expect(await approvals.listBySession(TEST_SESSION_ID)).toHaveLength(0)
        })

        it('iterates past earlier allow-level entries to find a later gated object (no false-positive short-circuit)', async () => {
            // Belt-and-braces for the allow-level case above: the lookup
            // must walk the whole tools[] array, not bail on the first
            // non-name-match. Here `agent-applications-list` is `level: 'allow'`
            // and `promote-create` is the gated (`approve`) entry — the model
            // calls `promote-create`, which sits SECOND in the array.
            const mcp = makeFakeMcp('posthog', POSTHOG_REF, {
                'agent-applications-revisions-promote-create': {
                    description: 'd',
                    result: { promoted: true },
                },
            })
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({
                principal: principalAlice,
                // Drop the sender stamp so the per-asker fast-path can't fire
                // and the only valid outcome is queue-on-the-gate.
                conversation: [{ role: 'user', content: 'promote it', timestamp: Date.now() }],
            })
            const out = await run(makeRev({ mcps: [POSTHOG_REF as never] }), session, {
                script: [
                    toolUse([
                        call('posthog__agent-applications-revisions-promote-create', {
                            application_id: 'app',
                        }),
                    ]),
                    stop('queued'),
                ],
                approvals,
                mcpClients: [mcp],
            })
            expect(out.state).toBe('completed')
            expect(mcp.calls).toEqual([])
            const rows = await approvals.listBySession(TEST_SESSION_ID)
            expect(rows).toHaveLength(1)
        })

        it('a client tool whose id collides with an MCP-shaped name is NOT gated by the MCP policy', async () => {
            // Author bug: `spec.tools[]` declares a client tool whose id
            // matches the model-visible `<prefix>__<remote>` shape AND
            // `spec.mcps[]` declares a gated entry for the same name. The
            // driver wrap must NOT pick up the MCP policy for the client
            // tool — that would surprise the client-tool dispatcher and
            // cross-couple two unrelated code paths. The mcpGate lookup
            // is gated behind `!ref` so this case dispatches normally.
            // (Review #7.)
            const collisionRef = AgentSpecSchema.parse({
                model: FAUX_MODEL_ID,
                mcps: [
                    {
                        kind: 'agent',
                        default_tool_approval: 'deny',
                        id: 'posthog',
                        url: 'https://example.com/posthog',
                        secrets: [],
                        tools: [
                            {
                                name: 'pingback',
                                level: 'approve',
                                approval_policy: { type: 'agent' },
                            },
                        ],
                    },
                ],
                tools: [
                    {
                        kind: 'client',
                        id: 'posthog__pingback',
                        description: 'Browser-side pingback handler.',
                        args_schema: {},
                    },
                ],
            }).mcps[0]
            const mcp = makeFakeMcp('posthog', collisionRef, {
                pingback: { description: 'd', result: { ok: true } },
            })
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({ principal: principalAlice })
            // The model calls the client-tool id (`posthog__pingback`). The
            // build-agent-tools collision-skip means the MCP version is
            // dropped from the surface; only the client tool remains under
            // that name. The wrap path must leave it alone.
            const out = await run(
                makeRev({
                    mcps: [collisionRef as never],
                    tools: [
                        {
                            kind: 'client',
                            id: 'posthog__pingback',
                            description: 'Browser-side pingback handler.',
                            args_schema: {},
                        },
                    ],
                }),
                session,
                {
                    script: [toolUse([call('posthog__pingback', { x: 1 })]), stop('done')],
                    approvals,
                    mcpClients: [mcp],
                }
            )
            // No approval row queued — the wrap declined to apply the MCP policy.
            expect(await approvals.listBySession(TEST_SESSION_ID)).toHaveLength(0)
            // Session reaches a terminal state (the client tool's runtime
            // dispatcher isn't wired in this faux harness, but the loop
            // outcome doesn't matter — what matters is "we didn't queue").
            expect(out.state).not.toBe('failed')
        })

        it('queues even when the last sender matches session.principal (no auto-dispatch / injection guard)', async () => {
            // Alice authed the session (`session.principal === alice`) and is
            // the one driving this turn (`conversation[last].sender === alice`).
            // There is no fast-path: being the asker is not consent to the
            // specific gated call the model emitted (which a prompt injection in
            // content the agent read could have steered). The wrap queues; the
            // real remote tool is never hit. Regression guard for the "approval
            // bypass" finding.
            const mcp = makeFakeMcp('posthog', POSTHOG_REF, {
                'agent-applications-revisions-promote-create': { description: 'd', result: { promoted: true } },
            })
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({
                principal: principalAlice,
                conversation: [{ role: 'user', content: 'promote it', sender: principalAlice, timestamp: Date.now() }],
            })
            const out = await run(makeRev({ mcps: [POSTHOG_REF as never] }), session, {
                script: [
                    toolUse([
                        call('posthog__agent-applications-revisions-promote-create', {
                            application_id: 'app',
                        }),
                    ]),
                    stop('queued'),
                ],
                approvals,
                mcpClients: [mcp],
            })
            expect(out.state).toBe('completed')
            // The real remote tool was NEVER called — the gate held.
            expect(mcp.calls).toEqual([])
            // Exactly one approval row queued for the gated call.
            const rows = await approvals.listBySession(TEST_SESSION_ID)
            expect(rows).toHaveLength(1)
            expect(rows[0].tool_name).toBe('posthog__agent-applications-revisions-promote-create')
            expect(rows[0].state).toBe('queued')
        })

        // ── Proxy-mode gating (large connection: >40 tools → helper tools) ──
        // A connection past the inline budget exposes only `<prefix>__call_tool`
        // / `explore_tools` / `get_tool_schema`; the underlying tool is named in
        // the `call_tool` args. Build a 42-tool fake MCP so `decideMcpExposure`
        // picks proxy mode, with one tool (`promote`) the author gated `approve`.
        const manyTools = (gated: string): Record<string, { description: string; result: unknown }> => {
            const tools: Record<string, { description: string; result: unknown }> = {
                [gated]: { description: 'gated tool', result: { promoted: true } },
            }
            for (let i = 0; i < 42; i++) {
                tools[`tool_${i}`] = { description: `tool ${i}`, result: { ok: true } }
            }
            return tools
        }
        const PROXY_REF: McpRef = AgentSpecSchema.parse({
            model: FAUX_MODEL_ID,
            mcps: [
                {
                    kind: 'agent',
                    default_tool_approval: 'allow',
                    id: 'big',
                    url: 'https://example.com/big',
                    secrets: [],
                    tools: [
                        { name: 'promote', level: 'approve', approval_policy: { type: 'principal', ttl_ms: 900_000 } },
                    ],
                },
            ],
        }).mcps[0]

        it('proxy call_tool with a PREFIXED tool_name still hits the per-tool approval gate (no doubled-prefix bypass)', async () => {
            // veria-ai (High): the model often passes the prefixed name it sees
            // (`big__promote`) as `call_tool`'s `tool_name`. The proxy strips the
            // prefix before dispatch, so the driver's approval gate must strip it
            // too — otherwise it keys the lookup on `big__big__promote`, misses
            // the `approve` override, and the gated tool runs without approval.
            const mcp = makeFakeMcp('big', PROXY_REF, manyTools('promote'))
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({
                principal: principalAlice,
                conversation: [{ role: 'user', content: 'promote it', timestamp: Date.now() }],
            })
            const out = await run(makeRev({ mcps: [PROXY_REF as never] }), session, {
                script: [
                    toolUse([
                        call('big__call_tool', { tool_name: 'big__promote', arguments: { application_id: 'a' } }),
                    ]),
                    stop('queued'),
                ],
                approvals,
                mcpClients: [mcp],
            })
            expect(out.state).toBe('completed')
            // Gate held: the underlying remote tool was never invoked.
            expect(mcp.calls).toEqual([])
            const rows = await approvals.listBySession(TEST_SESSION_ID)
            expect(rows).toHaveLength(1)
            // The row is keyed on the normalized underlying tool, not the doubled prefix.
            expect(rows[0].tool_name).toBe('big__promote')
            expect(rows[0].state).toBe('queued')
        })

        it('proxy call_tool gates a remote tool whose RAW name shadows a `<prefix>__` form (no unconditional-strip bypass)', async () => {
            // hex / veria (Medium): the proxy's `resolveRemoteName` prefers the
            // RAW arg when it exists in the catalog (only strips `<prefix>__`
            // when the stripped name resolves). The driver's gate used to strip
            // unconditionally, so a remote tool literally named `big__delete`
            // dispatched as `big__delete` but gated as `delete` — a missing
            // tools[] entry, `default_tool_approval: allow` falls through, and
            // the `approve` override on the real tool was bypassed. With both
            // paths sharing the same resolver, the gate keys on the actual
            // remote name and the queue holds. (Prompt-injection bypass guard.)
            const shadowRef: McpRef = AgentSpecSchema.parse({
                model: FAUX_MODEL_ID,
                mcps: [
                    {
                        kind: 'agent',
                        // `allow` default + an `approve` per-tool override is the
                        // exact configuration that the old bypass made unsafe.
                        default_tool_approval: 'allow',
                        id: 'big',
                        url: 'https://example.com/big',
                        secrets: [],
                        tools: [
                            {
                                name: 'big__delete',
                                level: 'approve',
                                approval_policy: { type: 'principal', ttl_ms: 900_000 },
                            },
                        ],
                    },
                ],
            }).mcps[0]
            const mcp = makeFakeMcp('big', shadowRef, manyTools('big__delete'))
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({
                principal: principalAlice,
                conversation: [{ role: 'user', content: 'delete it', timestamp: Date.now() }],
            })
            const out = await run(makeRev({ mcps: [shadowRef as never] }), session, {
                script: [
                    // Model passes the RAW remote name (which itself starts with
                    // `big__`). The proxy resolver prefers this raw form because
                    // it exists in the exposed catalog; the gate must agree.
                    toolUse([call('big__call_tool', { tool_name: 'big__delete', arguments: {} })]),
                    stop('queued'),
                ],
                approvals,
                mcpClients: [mcp],
            })
            expect(out.state).toBe('completed')
            // Gate held: the remote was NOT dispatched. (The bypass would show
            // up here as `mcp.calls` containing the `big__delete` invocation.)
            expect(mcp.calls).toEqual([])
            const rows = await approvals.listBySession(TEST_SESSION_ID)
            expect(rows).toHaveLength(1)
            // The approval row is keyed on `<prefix>__<resolvedRawName>` — the
            // doubled-prefix form a strip-less resolver produces here.
            expect(rows[0].tool_name).toBe('big__big__delete')
            expect(rows[0].state).toBe('queued')
        })

        it('proxy explore_tools stays ungated even under an approve default (synthetic helper, proxy-aware skip)', async () => {
            // Regression guard for the proxy-aware exemption: with the blanket
            // name-based exemption removed from lookupMcpToolApproval, the driver
            // must still skip the synthetic read-only helpers for a PROXIED
            // connection — otherwise catalog browsing would block on a human.
            const approveRef: McpRef = AgentSpecSchema.parse({
                model: FAUX_MODEL_ID,
                mcps: [
                    {
                        kind: 'agent',
                        default_tool_approval: 'approve',
                        id: 'big',
                        url: 'https://example.com/big',
                        secrets: [],
                    },
                ],
            }).mcps[0]
            const mcp = makeFakeMcp('big', approveRef, manyTools('promote'))
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({ principal: principalAlice })
            const out = await run(makeRev({ mcps: [approveRef as never] }), session, {
                script: [toolUse([call('big__explore_tools', { query: 'promote' })]), stop('listed')],
                approvals,
                mcpClients: [mcp],
            })
            expect(out.state).toBe('completed')
            // explore_tools ran (no approval queued) — read-only catalog browsing.
            expect(await approvals.listBySession(TEST_SESSION_ID)).toHaveLength(0)
        })
    })

    /**
     * Covers the gateway-metadata streamFn wrapper + the post-turn settled
     * cost fetch. Uses a recording `streamFn` injected via deps so we can
     * inspect the headers pi-ai would see, and a fake GatewayClient so we
     * can drive cost merge without hitting a real /v1/usage. The behaviour
     * here is load-bearing for the ai-gateway path: the Idempotency-Key lets
     * the gateway collapse pi-ai retries onto one billed row, and the post-turn
     * `getUsage` keyed by the gateway's OWN response id is the sole source of
     * `usage_total.cost_total` — key it wrong and cost stays zero forever.
     */
    describe('gateway metadata + post-turn settled cost', () => {
        // Build a streamFn that delegates to `streamSimple` but records every
        // call's options.headers. When `gatewayRequestId` is given it first
        // fires `onResponse` with that id in the (lowercased) `x-request-id`
        // header — the faux provider returns no response headers, so this
        // simulates the gateway stamping its server-minted settlement id.
        function recordingStreamFn(
            calls: Array<{ headers: Record<string, string> | undefined }>,
            gatewayRequestId?: string
        ): Parameters<typeof runSession>[2]['streamFn'] {
            return async (model, ctx, opts) => {
                calls.push({ headers: opts?.headers as Record<string, string> | undefined })
                if (gatewayRequestId) {
                    await opts?.onResponse?.({ status: 200, headers: { 'x-request-id': gatewayRequestId } }, model)
                }
                return streamSimple(model, ctx, opts)
            }
        }

        it('keys settled cost by the gateway response id, not the Idempotency-Key', async () => {
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            // The gateway mints this server-side and returns it in X-Request-ID;
            // the runner must fetch usage by THIS id, never its own outbound key.
            const GW_ID = 'a1b2c3d4e5f600112233445566778899'
            const getUsage = vi.fn(async (requestId: string) => ({
                request_id: requestId,
                team_id: 1,
                cost_usd: '0.42',
                settled_at: new Date().toISOString(),
            }))
            const session = makeSession()
            const out = await run(makeRev(), session, {
                script: [stop('hi back')],
                streamFn: recordingStreamFn(calls, GW_ID),
                gatewayHeaders: { 'X-PostHog-Distinct-Id': 'team:1:agent:app', 'X-PostHog-Trace-Id': TEST_SESSION_ID },
                gatewayUsage: { client: { getUsage } as never, phc: 'phc_test' },
                gatewayEmitsGenerations: true,
            })
            expect(out.state).toBe('completed')
            // One outbound call carrying the static gateway headers + the per-turn
            // Idempotency-Key. X-Request-Id is NOT sent (the gateway ignores any
            // inbound value and mints its own).
            expect(calls).toHaveLength(1)
            expect(calls[0].headers).toMatchObject({
                'X-PostHog-Distinct-Id': 'team:1:agent:app',
                'X-PostHog-Trace-Id': TEST_SESSION_ID,
            })
            const idempotencyKey = calls[0].headers?.['Idempotency-Key']
            expect(idempotencyKey).toMatch(new RegExp(`^agent:${TEST_SESSION_ID}:1:[0-9a-f-]{36}$`))
            expect(calls[0].headers ?? {}).not.toHaveProperty('X-Request-Id')
            // getUsage was keyed by the GATEWAY id from the response header, not
            // our Idempotency-Key (the old bug); the cost merged into usage_total.
            expect(getUsage).toHaveBeenCalledTimes(1)
            expect(getUsage).toHaveBeenCalledWith(GW_ID, { phc: 'phc_test' })
            expect(getUsage).not.toHaveBeenCalledWith(idempotencyKey, { phc: 'phc_test' })
            expect(session.usage_total.cost_total).toBeCloseTo(0.42, 5)
        })

        it('uses a unique Idempotency-Key per call so resumes never collide', async () => {
            // Regression: `outboundTurn` resets to 1 on every runSession, so a
            // key of just `agent:<session>:<turn>` made every follow-up's first
            // call reuse `agent:<session>:1`. The gateway then replayed the
            // first turn's cached response (24h Idempotency-Key window) instead
            // of calling the model, and the follow-up ended instantly with no
            // output. The per-call nonce must make each key distinct.
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            const gatewayHeaders = { 'X-PostHog-Trace-Id': TEST_SESSION_ID }
            const session = makeSession()
            // Two independent runSession invocations against the SAME session —
            // an initial turn followed by a /send-driven resume.
            await run(makeRev(), session, {
                script: [stop('first')],
                streamFn: recordingStreamFn(calls),
                gatewayHeaders,
            })
            await run(makeRev(), session, {
                script: [stop('second')],
                streamFn: recordingStreamFn(calls),
                gatewayHeaders,
            })
            expect(calls).toHaveLength(2)
            const firstKey = calls[0].headers?.['Idempotency-Key']
            const secondKey = calls[1].headers?.['Idempotency-Key']
            expect(firstKey).toMatch(new RegExp(`^agent:${TEST_SESSION_ID}:1:`))
            expect(secondKey).toMatch(new RegExp(`^agent:${TEST_SESSION_ID}:1:`))
            expect(secondKey).not.toBe(firstKey)
        })

        it('survives a getUsage NaN/failure without polluting cost_total', async () => {
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            const getUsage = vi.fn(async () => ({
                request_id: 'gw-nan',
                team_id: 1,
                cost_usd: 'not-a-number',
                settled_at: new Date().toISOString(),
            }))
            const session = makeSession()
            const out = await run(makeRev(), session, {
                script: [stop('hi back')],
                // Simulate the gateway returning an id so the cost fetch is reached.
                streamFn: recordingStreamFn(calls, 'gw-nan'),
                gatewayHeaders: {},
                gatewayUsage: { client: { getUsage } as never, phc: 'phc_test' },
                gatewayEmitsGenerations: true,
            })
            expect(out.state).toBe('completed')
            expect(getUsage).toHaveBeenCalledWith('gw-nan', { phc: 'phc_test' })
            expect(session.usage_total.cost_total).toBe(0)
        })

        it('fails open when the gateway returns no X-Request-ID: no getUsage, cost stays 0', async () => {
            // No gateway id → recordingStreamFn lets the faux provider fire
            // onResponse with empty headers (the gateway-misroute / header-strip
            // case). turnRequestIds never gets an id, so the cost fetch is
            // skipped cleanly instead of 404'ing on a bogus key.
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            const getUsage = vi.fn(async () => ({
                request_id: 'unused',
                team_id: 1,
                cost_usd: '9.99',
                settled_at: new Date().toISOString(),
            }))
            const session = makeSession()
            const out = await run(makeRev(), session, {
                script: [stop('hi back')],
                streamFn: recordingStreamFn(calls),
                gatewayHeaders: {},
                gatewayUsage: { client: { getUsage } as never, phc: 'phc_test' },
                gatewayEmitsGenerations: true,
            })
            expect(out.state).toBe('completed')
            expect(getUsage).not.toHaveBeenCalled()
            expect(session.usage_total.cost_total).toBe(0)
        })

        it('skips the wrapper entirely when neither gatewayHeaders nor gatewayUsage is set', async () => {
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            const out = await run(makeRev(), makeSession(), {
                script: [stop('ok')],
                streamFn: recordingStreamFn(calls),
            })
            expect(out.state).toBe('completed')
            // No Idempotency-Key / X-Request-Id injected when no gateway path.
            expect(calls[0].headers ?? {}).not.toHaveProperty('Idempotency-Key')
            expect(calls[0].headers ?? {}).not.toHaveProperty('X-Request-Id')
        })
    })

    /**
     * Multi-model fallback. The driver wraps the base streamFn with
     * `fallbackStreamFn` whenever `models.length > 1`. A pre-commit transient
     * failure on the primary falls over to the next model; a single-model spec
     * skips the wrapper entirely (legacy behaviour).
     */
    describe('multi-model fallback', () => {
        // A streamFn that fails model `a` once (pre-commit 429) then answers on
        // model `b`. Mirrors the faux provider's `start`→`error` shape so the
        // commit guard treats it as a pre-commit failure.
        const fallbackStreamFn = (): Parameters<typeof runSession>[2]['streamFn'] => {
            return (model) => {
                const stream = createAssistantMessageEventStream()
                queueMicrotask(() => {
                    if (model.id === 'a') {
                        const errored = fauxAssistantMessage('', {
                            stopReason: 'error',
                            errorMessage: '429 rate limit',
                        })
                        const evs: AssistantMessageEvent[] = [
                            { type: 'start', partial: fauxAssistantMessage('') },
                            { type: 'error', reason: 'error', error: errored },
                        ]
                        for (const e of evs) {
                            stream.push(e)
                        }
                        stream.end(errored)
                        return
                    }
                    const done = fauxAssistantMessage('recovered', { stopReason: 'stop' })
                    const partial = { ...done }
                    const evs: AssistantMessageEvent[] = [
                        { type: 'start', partial: fauxAssistantMessage('') },
                        { type: 'text_delta', contentIndex: 0, delta: 'recovered', partial },
                        { type: 'done', reason: 'stop', message: done },
                    ]
                    for (const e of evs) {
                        stream.push(e)
                    }
                    stream.end(done)
                })
                return stream
            }
        }

        it('falls over to the second model on a transient primary failure', async () => {
            const session = makeSession()
            const out = await run(makeRev(), session, {
                models: [{ model: fauxModel([stop('x')]) }, { model: fauxModel([stop('y')]) }].map((m, i) => ({
                    // Distinct ids so the streamFn can route per attempt.
                    model: { ...m.model, id: i === 0 ? 'a' : 'b' },
                })),
                streamFn: fallbackStreamFn(),
            })
            // The session completed on the fallback model's answer.
            expect(out.state).toBe('completed')
            const last = session.conversation.at(-1) as { role: string; content: unknown }
            expect(last.role).toBe('assistant')
        })

        it('tags the direct-path $ai_generation with the fallback attempt + fallback_from', async () => {
            // The observability contract for the feature: after a fallover the
            // emitted generation must carry which attempt answered (>0) and the
            // primary it fell back from, so AI observability can answer "did it
            // fall back, and off which model".
            const events: AnalyticsEvent[] = []
            const out = await run(makeRev(), makeSession(), {
                models: [{ model: fauxModel([stop('x')]) }, { model: fauxModel([stop('y')]) }].map((m, i) => ({
                    model: { ...m.model, id: i === 0 ? 'a' : 'b' },
                })),
                streamFn: fallbackStreamFn(),
                analytics: { write: async (batch: AnalyticsEvent[]) => void events.push(...batch) },
            })
            expect(out.state).toBe('completed')
            const gens = events.filter((e): e is AnalyticsGenerationEvent => e.kind === 'generation')
            expect(gens).toHaveLength(1)
            expect(gens[0].model_attempt).toBe(1)
            expect(gens[0].fallback_from).toBe('a')
        })

        it('cost mode pins to the conversation last-served model on resume (no primary probe)', async () => {
            // A resumed session whose last assistant turn ran on `b`. With the
            // default `optimize_for: cost`, the next turn must dispatch ONLY `b`
            // — not probe the priority primary `a` — so the cache stays warm.
            const dispatched: string[] = []
            const recordFn: Parameters<typeof runSession>[2]['streamFn'] = (model) => {
                dispatched.push(model.id)
                const stream = createAssistantMessageEventStream()
                queueMicrotask(() => {
                    const done = fauxAssistantMessage('ok', { stopReason: 'stop' })
                    stream.push({ type: 'start', partial: fauxAssistantMessage('') })
                    stream.push({ type: 'done', reason: 'stop', message: done })
                    stream.end(done)
                })
                return stream
            }
            const session = makeSession({
                conversation: [
                    { role: 'user', content: 'hi', timestamp: Date.now() },
                    { role: 'assistant', content: [], model: 'b', timestamp: Date.now() } as never,
                ],
            })
            const out = await run(makeRev(), session, {
                models: [{ model: fauxModel([stop('x')]) }, { model: fauxModel([stop('y')]) }].map((m, i) => ({
                    model: { ...m.model, id: i === 0 ? 'a' : 'b' },
                })),
                streamFn: recordFn,
            })
            expect(out.state).toBe('completed')
            expect(dispatched).toEqual(['b'])
        })

        // Regression: a real provider echoes the PROVIDER-SAFE tool name
        // (`posthog_meta-end-turn`), not the `@posthog/...` original. The
        // sanitizing wrapper must translate it back, and on the multi-model path
        // it must run OUTSIDE the fallback wrapper — the fallback re-emits the
        // `done` event (safe name) into a fresh stream, so an inner sanitizing
        // result() never reaches the loop. The faux provider can't exercise this
        // (it echoes the original verbatim), so we emit the safe name by hand.
        it('translates a provider-safe tool name echoed through the fallback wrapper', async () => {
            let calls = 0
            const safeEndTurn = (): Parameters<typeof runSession>[2]['streamFn'] => {
                return () => {
                    calls++
                    const stream = createAssistantMessageEventStream()
                    queueMicrotask(() => {
                        // First turn: end_turn under its provider-safe name. If the
                        // map misses, the loop returns "tool not found" and keeps
                        // going — a second call. With the fix it's intercepted and
                        // the turn terminates after one call.
                        const done =
                            calls === 1
                                ? fauxAssistantMessage([fauxToolCall('posthog_meta-end-turn', {})], {
                                      stopReason: 'toolUse',
                                  })
                                : fauxAssistantMessage('fallthrough', { stopReason: 'stop' })
                        stream.push({ type: 'start', partial: fauxAssistantMessage('') })
                        stream.push({ type: 'done', reason: calls === 1 ? 'toolUse' : 'stop', message: done })
                        stream.end(done)
                    })
                    return stream
                }
            }
            const out = await run(makeRev(), makeSession(), {
                models: [{ model: fauxModel([stop('x')]) }, { model: fauxModel([stop('y')]) }].map((m, i) => ({
                    model: { ...m.model, id: i === 0 ? 'a' : 'b' },
                })),
                streamFn: safeEndTurn(),
            })
            expect(out.state).toBe('completed')
            // The safe name resolved to @posthog/meta-end-turn and terminated the
            // turn on the first model call — no "not found" + retry.
            expect(calls).toBe(1)
        })
    })

    /**
     * Generation-event emission splits by path: on the gateway path the gateway
     * emits the cost-bearing `$ai_generation`, so the runner must NOT emit its
     * own (double-counting); off the gateway path it emits one, without cost
     * (pi-ai's estimate is never used — ingestion prices it from the catalog).
     * Spans/trace are runner-only and emitted on both paths.
     */
    describe('analytics generation emission', () => {
        function recordingSink(events: AnalyticsEvent[]): AnalyticsSink {
            return { write: async (batch) => void events.push(...batch) }
        }

        it('suppresses the runner $ai_generation on the gateway path; still emits the trace', async () => {
            const events: AnalyticsEvent[] = []
            const out = await run(makeRev(), makeSession(), {
                script: [stop('hi back')],
                analytics: recordingSink(events),
                gatewayEmitsGenerations: true,
            })
            expect(out.state).toBe('completed')
            expect(events.filter((e) => e.kind === 'generation')).toHaveLength(0)
            expect(events.some((e) => e.kind === 'trace')).toBe(true)
        })

        it('emits one $ai_generation without cost on the direct path', async () => {
            const events: AnalyticsEvent[] = []
            const out = await run(makeRev(), makeSession(), {
                script: [stop('hi back')],
                analytics: recordingSink(events),
            })
            expect(out.state).toBe('completed')
            const gens = events.filter((e): e is AnalyticsGenerationEvent => e.kind === 'generation')
            expect(gens).toHaveLength(1)
            expect(gens[0].cost_usd).toBeUndefined()
        })
    })

    /**
     * The chat stop button: ingress publishes a `cancel` bus event (caught by
     * the runner's existing per-session subscription) and writes the durable
     * `cancelled` state. The runner interrupts the in-flight turn and reopens
     * the session as `completed` — open, restartable — rather than re-queuing
     * it (shutdown) or marking it terminal.
     */
    describe('cancel / interrupt', () => {
        it('reopens as completed (turns=0) when the session was cancelled before the run started', async () => {
            // The publish→subscribe race / a queued session marked cancelled
            // before claim: the bus event is gone, but the durable state isn't.
            const session = makeSession()
            const out = await run(makeRev(), session, {
                script: [stop('never')],
                getSessionState: async () => 'cancelled',
            })
            expect(out).toEqual({ state: 'completed', turns: 0 })
            // The model never ran — only the seeded user message is present.
            expect(session.conversation).toHaveLength(1)
        })

        it('a cancel mid-run stops between turns and reopens as completed', async () => {
            const session = makeSession()
            let published = false
            const streamFn: Parameters<typeof runSession>[2]['streamFn'] = async (model, ctx, opts) => {
                if (!published) {
                    published = true
                    await driverTestBus.publish({
                        session_id: session.id,
                        kind: 'cancel',
                        data: {},
                        ts: new Date().toISOString(),
                    })
                    // Let the runner's subscription deliver + abort before this
                    // turn ends (local Redis round-trips in ~1ms; ample margin).
                    await new Promise((r) => setTimeout(r, 150))
                }
                return streamSimple(model, ctx, opts)
            }
            const out = await run(makeRev({ tools: [{ kind: 'native', id: '@posthog/query' }] }), session, {
                // Turn 1 calls a tool (loop would continue); the cancel stops it
                // before turn 2's `stop` is ever reached.
                script: [toolUse([call('@posthog/query', { query: 'x' })]), stop('should not reach')],
                streamFn,
            })
            expect(out).toEqual({ state: 'completed', turns: 1 })
        })
    })
})
