import type { S3Client } from '@aws-sdk/client-s3'
import {
    type AssistantMessage,
    fauxAssistantMessage,
    fauxToolCall,
    type Model,
    registerFauxProvider,
    streamSimple,
    type ToolCall,
} from '@earendil-works/pi-ai'
import { Pool } from 'pg'

import {
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
    principalsMatch,
    RedisSessionEventBus,
    S3BundleStore,
    SessionPrincipal,
    wipeTestPrefix,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'localhost:9092'

import { buildApprovalDecidedMarker } from './approval-marker'
import { runSession } from './driver'
import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'
import { findLastUserSender, type IsAskerInApproverScope } from './per-asker-auth'

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
        model: fauxModel((over.script as AssistantMessage[]) ?? [stop('ok')]),
        bundle,
        sandbox: null,
        integrations: {},
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
     * the wrap path for the MCP variant + the `session_principal` per-asker
     * fast-path that the concierge case relies on.
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
        // defaults (`allow_edit`, `allow_agent_approver`) get materialised
        // — the runner reads the strict shape, not the zod input form.
        const POSTHOG_REF: McpRef = AgentSpecSchema.parse({
            model: FAUX_MODEL_ID,
            mcps: [
                {
                    kind: 'external',
                    id: 'posthog',
                    url: 'https://app.posthog.com/api/mcp',
                    secrets: [],
                    tools: [
                        'agent-applications-list',
                        {
                            name: 'agent-applications-revisions-promote-create',
                            requires_approval: true,
                            approval_policy: { approvers: ['session_principal'], ttl_ms: 900_000 },
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
            // dispatcher's MCP lookup finds `requires_approval: true` on the
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

        it('does NOT queue when the matching tools[] entry is bare-string (inclusion only)', async () => {
            // `agent-applications-list` is in tools[] as a bare string —
            // included but no gating. The dispatcher's MCP lookup returns
            // null, the native lookup doesn't match either, so the tool
            // dispatches directly. Sibling case below pins iteration order
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

        it('iterates past earlier bare-string entries to find a later gated object (no false-positive short-circuit)', async () => {
            // Belt-and-braces for the bare-string case above: the lookup
            // must walk the whole tools[] array, not bail on the first
            // non-name-match. Here `agent-applications-list` is a bare
            // string and `promote-create` is the gated object — the model
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
                        kind: 'external',
                        id: 'posthog',
                        url: 'https://example.com/posthog',
                        secrets: [],
                        tools: [
                            {
                                name: 'pingback',
                                requires_approval: true,
                                approval_policy: { approvers: ['team_admins'] },
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

        it('session_principal per-asker fast-path: dispatches directly when last sender matches session.principal', async () => {
            // Alice authed the session (`session.principal === alice`) and
            // is the one driving this turn (`conversation[last].sender === alice`).
            // The per-asker check returns true on the `session_principal`
            // branch (no DB roundtrip), the wrap runs the real tool, and no
            // approval row is created.
            const mcp = makeFakeMcp('posthog', POSTHOG_REF, {
                'agent-applications-revisions-promote-create': { description: 'd', result: { promoted: true } },
            })
            const approvals = new PgApprovalStore(pool)
            const session = makeSession({
                principal: principalAlice,
                conversation: [{ role: 'user', content: 'promote it', sender: principalAlice, timestamp: Date.now() }],
            })
            // Direct stub — same contract as `makePerAskerAuth` returns. We
            // route through `principalsMatch` to mirror the production check.
            const out = await run(makeRev({ mcps: [POSTHOG_REF as never] }), session, {
                script: [
                    toolUse([
                        call('posthog__agent-applications-revisions-promote-create', {
                            application_id: 'app',
                        }),
                    ]),
                    stop('done'),
                ],
                approvals,
                mcpClients: [mcp],
                isAskerInApproverScope: (async (conversation, _teamId, scope, sessionPrincipal) => {
                    if (!scope.includes('session_principal')) {
                        return false
                    }
                    const sender = findLastUserSender(conversation)
                    return Boolean(sender && principalsMatch(sessionPrincipal, sender))
                }) satisfies IsAskerInApproverScope,
            })
            expect(out.state).toBe('completed')
            // Fast-path ran the real remote tool exactly once.
            expect(mcp.calls).toEqual([
                { name: 'agent-applications-revisions-promote-create', args: { application_id: 'app' } },
            ])
            // No approval row queued — that's the whole point of the fast-path.
            expect(await approvals.listBySession(TEST_SESSION_ID)).toHaveLength(0)
        })
    })

    /**
     * Covers the gateway-metadata streamFn wrapper + the post-turn settled
     * cost fetch. Uses a recording `streamFn` injected via deps so we can
     * inspect the headers pi-ai would see, and a fake GatewayClient so we
     * can drive cost merge without hitting a real /v1/usage. The behaviour
     * here is load-bearing for the ai-gateway path — without the per-turn
     * `request_id` stamp + Idempotency-Key, the gateway can't dedupe pi-ai
     * retries onto a single billed row, and without the post-turn
     * `getUsage` merge `usage_total.cost_total` stays zero forever.
     */
    describe('gateway metadata + post-turn settled cost', () => {
        // Build a streamFn that just delegates to `streamSimple` but records
        // every call's options.headers in the provided array.
        function recordingStreamFn(
            calls: Array<{ headers: Record<string, string> | undefined }>
        ): Parameters<typeof runSession>[2]['streamFn'] {
            return (model, ctx, opts) => {
                calls.push({ headers: opts?.headers as Record<string, string> | undefined })
                return streamSimple(model, ctx, opts)
            }
        }

        it('stamps Idempotency-Key + X-Request-Id per turn and merges settled cost', async () => {
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            const getUsage = vi.fn(async (requestId: string) => ({
                request_id: requestId,
                team_id: 1,
                cost_usd: '0.42',
                settled_at: new Date().toISOString(),
            }))
            const session = makeSession()
            const out = await run(makeRev(), session, {
                script: [stop('hi back')],
                streamFn: recordingStreamFn(calls),
                gatewayHeaders: { 'X-PostHog-Distinct-Id': 'team:1:agent:app', 'X-PostHog-Trace-Id': TEST_SESSION_ID },
                gatewayUsage: { client: { getUsage } as never, phc: 'phc_test' },
                useGatewayCost: true,
            })
            expect(out.state).toBe('completed')
            // One outbound call, headers carry the static gateway headers
            // PLUS the per-turn id matching the `agent:<session>:<turn>` shape.
            expect(calls).toHaveLength(1)
            expect(calls[0].headers).toMatchObject({
                'X-PostHog-Distinct-Id': 'team:1:agent:app',
                'X-PostHog-Trace-Id': TEST_SESSION_ID,
                'Idempotency-Key': `agent:${TEST_SESSION_ID}:1`,
                'X-Request-Id': `agent:${TEST_SESSION_ID}:1`,
            })
            // getUsage was called for that exact request id; the returned
            // cost landed in usage_total.
            expect(getUsage).toHaveBeenCalledTimes(1)
            expect(getUsage).toHaveBeenCalledWith(`agent:${TEST_SESSION_ID}:1`, { phc: 'phc_test' })
            expect(session.usage_total.cost_total).toBeCloseTo(0.42, 5)
        })

        it('survives a getUsage NaN/failure without polluting cost_total', async () => {
            const calls: Array<{ headers: Record<string, string> | undefined }> = []
            const getUsage = vi.fn(async () => ({
                request_id: `agent:${TEST_SESSION_ID}:1`,
                team_id: 1,
                cost_usd: 'not-a-number',
                settled_at: new Date().toISOString(),
            }))
            const session = makeSession()
            const out = await run(makeRev(), session, {
                script: [stop('hi back')],
                streamFn: recordingStreamFn(calls),
                gatewayHeaders: {},
                gatewayUsage: { client: { getUsage } as never, phc: 'phc_test' },
                useGatewayCost: true,
            })
            expect(out.state).toBe('completed')
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
