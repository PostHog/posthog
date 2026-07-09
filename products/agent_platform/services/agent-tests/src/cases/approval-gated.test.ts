/**
 * Approval-gated tools: real e2e contract for v0.
 *
 * Pins the wire-level behaviour for approval-gated tools. The cases below
 * collectively cover the loop:
 *
 *   model proposes a gated call
 *     → dispatcher intercepts and writes an `agent_tool_approval_request`
 *     → synthetic queued tool_result lands in the conversation
 *     → session does NOT park
 *   approver POSTs janitor /approvals/<id>/decide
 *     → janitor marks the row `approving`, drops an approval-decided marker
 *       into the session's pending_inputs, flips session state to `queued`
 *   runner picks up the wake
 *     → recognises the marker, dispatches the tool via the same path it
 *       uses for any other tool, finalises the approval row, transforms
 *       the marker into the real synthetic tool_result, continues the turn
 *
 * These tests are intentionally written *before* the implementation lands —
 * they fail today on every case past "deploy + run" and turn green as
 * each slice in plan §10 ships.
 *
 * The Django proxy is NOT exercised here. The harness only runs ingress +
 * runner + janitor. Django-side auth + janitor_client proxy gets unit
 * tests in `products/agent_platform/backend/`.
 */

import { fauxToolCall } from '@earendil-works/pi-ai'
import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fakeAuthProvider, fauxCallTool, fauxText } from '../harness'

// `@posthog/*` data tools act as the connected PostHog user, so the cases that
// actually execute one (case 1) run as a posthog-authed caller.
const APPROVAL_PAT = 'approval-pat'
import { fauxToolUse } from '../harness/faux'

/**
 * Parse the synthetic-approval payload out of a conversation message. The
 * dispatcher stuffs the approval JSON into a single TextContent so the
 * model sees it as ordinary content. Two roles carry the envelope:
 *   - `toolResult` — the QUEUED intercept result, immediately following
 *     the model's tool_call (Anthropic-compatible pairing).
 *   - `user`      — the WAKE result (approved / rejected / expired), pushed
 *     when the approval lands later. Has to be a user message because by
 *     then the prior assistant message no longer carries the matching
 *     tool_use, and Anthropic rejects orphaned tool_results.
 *
 * Returns null when the message isn't a synthetic approval envelope.
 */
function parseApprovalPayload(msg: unknown): {
    request_id: string
    state: 'queued' | 'approved' | 'rejected' | 'expired'
    approval_url?: string
    approver_hint?: string
    prior_decision?: { state: string; reason?: string }
    decided_by?: string
    edited_args?: boolean
    reason?: string
    result?: unknown
    error?: string
} | null {
    const m = msg as { role?: string; content?: string | Array<{ type?: string; text?: string }> }
    if (m.role !== 'toolResult' && m.role !== 'user') {
        return null
    }
    let text: string | undefined
    if (Array.isArray(m.content)) {
        text = m.content[0]?.text
    } else if (typeof m.content === 'string') {
        text = m.content
    }
    if (typeof text !== 'string') {
        return null
    }
    try {
        const parsed = JSON.parse(text)
        if (parsed && typeof parsed === 'object' && 'approval' in parsed) {
            return { ...parsed.approval, ...(parsed.result !== undefined ? { result: parsed.result } : {}) }
        }
    } catch {
        return null
    }
    return null
}

function findApproval(
    conversation: unknown[],
    state?: string,
    opts: { from?: 'first' | 'last' } = {}
): ReturnType<typeof parseApprovalPayload> {
    const from = opts.from ?? 'first'
    const order = from === 'last' ? [...conversation].reverse() : conversation
    for (const m of order) {
        const a = parseApprovalPayload(m)
        if (a && (!state || a.state === state)) {
            return a
        }
    }
    return null
}

describe('approval-gated tools: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({ authProvider: fakeAuthProvider({ posthog: APPROVAL_PAT }) })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    /**
     * Helper — deploy an agent whose tool list contains exactly one
     * gated entry. Adds the matching non-gated companion when the case
     * needs a mixed-turn surface (case 6).
     */
    async function deployGatedAgent(opts: {
        slug: string
        toolId: string
        kind?: 'native' | 'custom'
        path?: string
        allowEdit?: boolean
        /** Approval authority. Omit for the `principal` default. */
        approvalType?: 'principal' | 'agent'
        extraTools?: Array<Record<string, unknown>>
        files?: Record<string, string>
        auth?: Record<string, unknown>
    }): Promise<{ application: { id: string } }> {
        const gated =
            opts.kind === 'custom'
                ? {
                      kind: 'custom' as const,
                      id: opts.toolId,
                      path: opts.path ?? `tools/${opts.toolId}/`,
                      requires_approval: true,
                      approval_policy: {
                          allow_edit: !!opts.allowEdit,
                          ...(opts.approvalType ? { type: opts.approvalType } : {}),
                      },
                  }
                : {
                      kind: 'native' as const,
                      id: opts.toolId,
                      requires_approval: true,
                      approval_policy: {
                          allow_edit: !!opts.allowEdit,
                          ...(opts.approvalType ? { type: opts.approvalType } : {}),
                      },
                  }
        return c.deployAgent({
            slug: opts.slug,
            spec: { tools: [gated, ...(opts.extraTools ?? [])], ...(opts.auth ? { auth: opts.auth } : {}) },
            files: opts.files,
        })
    }

    /** Fetch the approval rows for a given application via janitor. */
    async function listApprovals(
        applicationId: string,
        state?: string
    ): Promise<Array<{ id: string; state: string; tool_name: string }>> {
        const res = await request(c.janitor)
            .get('/approvals')
            .query({ application_id: applicationId, ...(state ? { state } : {}) })
        expect(res.status).toBe(200)
        return res.body.results as Array<{ id: string; state: string; tool_name: string }>
    }

    /** Approver decides. Optional edited_args/reason mirror the plan §4.3 payload. */
    async function decide(
        approvalId: string,
        body: {
            decision: 'approve' | 'reject'
            decided_by: string
            edited_args?: Record<string, unknown>
            reason?: string
        }
    ): Promise<unknown> {
        const res = await request(c.janitor).post(`/approvals/${approvalId}/decide`).send(body)
        expect(res.status).toBe(200)
        return res.body
    }

    // ─────────────────────────────────────────────────────────────
    // Case 1 — happy path.
    // Gated native call queues, approver approves, runner dispatches the
    // real tool, model wraps up with a follow-up assistant text.
    // ─────────────────────────────────────────────────────────────
    it('case 1: queue → approve → real result → session completes', async () => {
        c.setScript([
            // Turn 1: model proposes the gated call.
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            // Turn 2: model reacts to the synthetic queued result (would
            // typically tell the user where to approve). Session ends here.
            fauxText('queued for approval'),
            // Turn 3: after approval wake, model wraps up.
            fauxText('done'),
        ])
        const { application } = await deployGatedAgent({
            slug: 'gated-1',
            toolId: '@posthog/query',
            auth: { modes: [{ type: 'posthog' }] },
        })

        const run = await request(c.ingress)
            .post('/agents/gated-1/run')
            .set('authorization', `Bearer ${APPROVAL_PAT}`)
            .send({ message: 'go' })
        expect(run.status).toBe(200)
        const sid = run.body.session_id

        await c.drain()

        // Session did NOT park. The synthetic queued result is in conversation.
        let session = await c.queue.get(sid)
        expect(session).not.toBeNull()
        expect(session!.state).not.toBe('waiting')
        const queued = findApproval(session!.conversation, 'queued')
        expect(queued).not.toBeNull()
        expect(queued!.request_id).toMatch(/^[0-9a-f-]+$/)
        expect(queued!.approval_url).toMatch(/\/approvals\?request=/)
        // Default policy is `principal`, so the hint points at the session's own
        // principal (not an owner/admin — that's the `agent` type).
        expect(queued!.approver_hint).toMatch(/person who started this session/i)

        // The approval is queryable via janitor.
        const approvals = await listApprovals(application.id, 'queued')
        expect(approvals).toHaveLength(1)
        expect(approvals[0].id).toBe(queued!.request_id)
        expect(approvals[0].tool_name).toBe('@posthog/query')

        // Approver approves. Janitor wakes the session.
        await decide(queued!.request_id, {
            decision: 'approve',
            decided_by: '00000000-0000-0000-0000-000000000001',
        })

        await c.drain()

        session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')

        // Real tool result + the "this was approved" envelope are in conversation.
        const approved = findApproval(session!.conversation, 'approved')
        expect(approved).not.toBeNull()
        expect(approved!.result).toMatchObject({ rows: [{ query: 'select 1' }] })
        expect(approved!.decided_by).toBe('00000000-0000-0000-0000-000000000001')

        // And the model's follow-up text landed.
        const assistantMessages = session!.conversation.filter(
            (m) => (m as { role: string }).role === 'assistant'
        ) as Array<{
            content: Array<{ type: string; text?: string }>
        }>
        const finalText = assistantMessages[assistantMessages.length - 1]
        expect(finalText.content[0].text).toBe('done')
    })

    // ─────────────────────────────────────────────────────────────
    // Case 1b — agent-level approval (owner/admin authority).
    // Same queue → approve → dispatch flow as case 1, but the policy is
    // `type: 'agent'`: the queued hint points at an owner/admin (not the
    // principal), and the decision is the one Django forwards to the janitor.
    // Proves an agent-type row flows all the way through decide → wake →
    // dispatch (Django's team-admin authz over the decide is covered separately
    // in backend/tests/test_approvals_api.py).
    // ─────────────────────────────────────────────────────────────
    it('case 1b: agent-type queue → approve → real result → completes', async () => {
        c.setScript([
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            fauxText('queued for approval'),
            fauxText('done'),
        ])
        const { application } = await deployGatedAgent({
            slug: 'gated-agent-type',
            toolId: '@posthog/query',
            approvalType: 'agent',
            auth: { modes: [{ type: 'posthog' }] },
        })

        const run = await request(c.ingress)
            .post('/agents/gated-agent-type/run')
            .set('authorization', `Bearer ${APPROVAL_PAT}`)
            .send({ message: 'go' })
        expect(run.status).toBe(200)
        const sid = run.body.session_id

        await c.drain()

        const queued = findApproval((await c.queue.get(sid))!.conversation, 'queued')
        expect(queued).not.toBeNull()
        // Agent-type → the hint points at an owner/admin, not the principal.
        expect(queued!.approver_hint).toMatch(/owner or admin/i)

        const approvals = await listApprovals(application.id, 'queued')
        expect(approvals).toHaveLength(1)
        expect(approvals[0].id).toBe(queued!.request_id)

        // Decide via the janitor route — the path Django forwards an owner/admin
        // console decision to.
        await decide(queued!.request_id, {
            decision: 'approve',
            decided_by: '00000000-0000-0000-0000-000000000001',
        })

        await c.drain()

        const session = await c.queue.get(sid)
        expect(session!.state).toBe('completed')
        const approved = findApproval(session!.conversation, 'approved')
        expect(approved).not.toBeNull()
        expect(approved!.result).toMatchObject({ rows: [{ query: 'select 1' }] })
        expect(approved!.decided_by).toBe('00000000-0000-0000-0000-000000000001')
    })

    // ─────────────────────────────────────────────────────────────
    // Case 2 — reject path.
    // Approver says no; model sees a rejected synthetic result and can
    // keep talking to the user (here it produces a closing message).
    // ─────────────────────────────────────────────────────────────
    it('case 2: reject → model sees rejection + reason, continues turn', async () => {
        c.setScript([
            // Turn 1: model proposes.
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            // Turn 2: pre-rejection reaction.
            fauxText('queued for approval'),
            // Turn 3: post-rejection reaction.
            fauxText('understood, will stop'),
        ])
        const { application } = await deployGatedAgent({ slug: 'gated-2', toolId: '@posthog/query' })

        const run = await request(c.ingress).post('/agents/gated-2/run').send({ message: 'go' })
        await c.drain()

        const [pending] = await listApprovals(application.id, 'queued')
        expect(pending).not.toBeUndefined()

        await decide(pending.id, {
            decision: 'reject',
            decided_by: '00000000-0000-0000-0000-000000000002',
            reason: 'amount too high',
        })

        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).toBe('completed')

        const rejected = findApproval(session!.conversation, 'rejected')
        expect(rejected).not.toBeNull()
        expect(rejected!.reason).toBe('amount too high')
        expect(rejected!.decided_by).toBe('00000000-0000-0000-0000-000000000002')

        // Row state in janitor matches.
        const allRows = await listApprovals(application.id)
        expect(allRows.find((r) => r.id === pending.id)?.state).toBe('rejected')
    })

    // ─────────────────────────────────────────────────────────────
    // Case 3 — idempotency.
    // The model calls the same tool twice in one turn with reordered keys
    // (same canonical args). Both refs dedupe to the same approval row.
    // ─────────────────────────────────────────────────────────────
    it('case 3: two calls with same canonical args dedupe to one approval row', async () => {
        c.setScript([
            fauxToolUse([
                fauxToolCall('@posthog/query', { project_id: 1, query: 'select 1', limit: 5 }),
                fauxToolCall('@posthog/query', { limit: 5, query: 'select 1', project_id: 1 }),
            ]),
            fauxText('queued'),
        ])
        const { application } = await deployGatedAgent({ slug: 'gated-3', toolId: '@posthog/query' })

        await request(c.ingress).post('/agents/gated-3/run').send({ message: 'go' })
        await c.drain()

        const approvals = await listApprovals(application.id)
        expect(approvals.filter((r) => r.state === 'queued')).toHaveLength(1)
    })

    // ─────────────────────────────────────────────────────────────
    // Case 4 — re-issue after rejection surfaces prior_decision.
    // ─────────────────────────────────────────────────────────────
    it('case 4: re-issue after rejection creates a fresh row with prior_decision', async () => {
        c.setScript([
            // Turn 1: initial gated call.
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            // Turn 2: pre-rejection reaction; session completes here.
            fauxText('queued, will share link'),
            // Turn 3: post-rejection re-try (same args; per plan §4.4).
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            // Turn 4: reaction to the new queued result.
            fauxText('ok'),
        ])
        const { application } = await deployGatedAgent({ slug: 'gated-4', toolId: '@posthog/query' })

        const run = await request(c.ingress).post('/agents/gated-4/run').send({ message: 'go' })
        await c.drain()

        const [first] = await listApprovals(application.id, 'queued')
        await decide(first.id, {
            decision: 'reject',
            decided_by: '00000000-0000-0000-0000-000000000003',
            reason: 'try smaller',
        })
        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        // The re-issue is the *latest* queued result — the original
        // queued result also stayed in the conversation as audit, but
        // it has no prior_decision since it was the first attempt.
        const newQueued = findApproval(session!.conversation, 'queued', { from: 'last' })
        expect(newQueued).not.toBeNull()
        expect(newQueued!.prior_decision?.state).toBe('rejected')
        expect(newQueued!.prior_decision?.reason).toBe('try smaller')

        // A second row exists.
        const queued = await listApprovals(application.id, 'queued')
        expect(queued).toHaveLength(1)
        expect(queued[0].id).not.toBe(first.id)
    })

    // ─────────────────────────────────────────────────────────────
    // Case 5 — expiry sweep flips queued → expired and wakes the session.
    // ─────────────────────────────────────────────────────────────
    it('case 5: janitor sweep expires queued rows past TTL', async () => {
        c.setScript([
            // Turn 1: gated call.
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            // Turn 2: pre-expiry reaction; session completes here.
            fauxText('queued for approval'),
            // Turn 3: post-expiry reaction.
            fauxText('ack'),
        ])
        const { application } = await deployGatedAgent({ slug: 'gated-5', toolId: '@posthog/query' })
        const run = await request(c.ingress).post('/agents/gated-5/run').send({ message: 'go' })
        await c.drain()

        const [queued] = await listApprovals(application.id, 'queued')

        // Force the row past its TTL via the DB. The sweep does the rest.
        await c.pool.query(
            `UPDATE agent_tool_approval_request SET expires_at = NOW() - interval '1 minute' WHERE id = $1`,
            [queued.id]
        )

        const sweep = await request(c.janitor).post('/sweep')
        expect(sweep.status).toBe(200)

        await c.drain()

        const expiredRow = (await listApprovals(application.id)).find((r) => r.id === queued.id)
        expect(expiredRow?.state).toBe('expired')

        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).toBe('completed')
        const expired = findApproval(session!.conversation, 'expired')
        expect(expired).not.toBeNull()
    })

    // ─────────────────────────────────────────────────────────────
    // Case 6 — mixed turn: one gated tool + one non-gated tool in the same
    // assistant message. Non-gated dispatches normally; gated queues.
    // Session never parks.
    // ─────────────────────────────────────────────────────────────
    it('case 6: mixed turn — non-gated tool dispatches, gated tool queues', async () => {
        c.setScript([
            fauxToolUse([
                fauxToolCall('@posthog/query', { project_id: 1, query: 'gated-call' }),
                fauxToolCall('@posthog/memory-list', {}),
            ]),
            fauxText('mixed done'),
        ])
        await c.deployAgent({
            slug: 'gated-6',
            spec: {
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/query',
                        requires_approval: true,
                        approval_policy: { allow_edit: false },
                    },
                    { kind: 'native', id: '@posthog/memory-list' },
                ],
            },
        })
        const run = await request(c.ingress).post('/agents/gated-6/run').send({ message: 'mix' })
        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).not.toBe('waiting')

        // Gated → synthetic queued result.
        expect(findApproval(session!.conversation, 'queued')).not.toBeNull()

        // Non-gated → real tool result.
        const realResults = session!.conversation.filter((m) => {
            const cast = m as { role: string; toolName?: string }
            return cast.role === 'toolResult' && cast.toolName === '@posthog/memory-list'
        })
        expect(realResults).toHaveLength(1)
    })

    // ─────────────────────────────────────────────────────────────
    // Case 7 — custom (sandboxed) tool gating. On approve the runner
    // dispatches through the InProcessSandboxPool path the same as it
    // would have without gating.
    // ─────────────────────────────────────────────────────────────
    it('case 7: custom sandboxed tool runs through sandbox after approval', async () => {
        // Minimal compiled custom tool — echoes back its args. Uses the
        // same CommonJS-with-`actions` shape the in-process sandbox expects;
        // see custom-tool-sandbox.test.ts for the contract.
        const COMPILED = `
            module.exports = {
                id: "echo-tool",
                actions: {
                    default: (args) => ({ echoed: args }),
                },
            }
        `
        c.setScript([fauxCallTool('echo-tool', { ping: 'pong' }), fauxText('queued'), fauxText('approved-run-done')])
        const { application } = await deployGatedAgent({
            slug: 'gated-7',
            toolId: 'echo-tool',
            kind: 'custom',
            path: 'tools/echo-tool/',
            files: {
                'tools/echo-tool/compiled.js': COMPILED,
                'tools/echo-tool/schema.json': JSON.stringify({
                    description: 'Echo',
                    args_schema: { type: 'object', properties: { ping: { type: 'string' } } },
                    returns: { type: 'object' },
                }),
            },
        })

        const run = await request(c.ingress).post('/agents/gated-7/run').send({ message: 'go' })
        await c.drain()

        const [queued] = await listApprovals(application.id, 'queued')
        await decide(queued.id, { decision: 'approve', decided_by: '00000000-0000-0000-0000-000000000007' })
        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        expect(session!.state).toBe('completed')
        const approved = findApproval(session!.conversation, 'approved')
        expect(approved).not.toBeNull()
        expect(approved!.result).toMatchObject({ echoed: { ping: 'pong' } })
    })

    // ─────────────────────────────────────────────────────────────
    // Case 8 — the queued envelope always carries approval_url + approver_hint,
    // regardless of the connecting client (no per-client suppression).
    // ─────────────────────────────────────────────────────────────
    it('case 8: queued envelope always includes approval_url + approver_hint', async () => {
        c.setScript([
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            fauxText('queued for approval'),
        ])
        await deployGatedAgent({
            slug: 'gated-8',
            toolId: '@posthog/query',
            auth: { modes: [{ type: 'posthog' }] },
        })

        const run = await request(c.ingress)
            .post('/agents/gated-8/run')
            .set('authorization', `Bearer ${APPROVAL_PAT}`)
            .send({ message: 'go', supported_client_tools: ['connect_mcp'] })
        expect(run.status).toBe(200)
        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        const queued = findApproval(session!.conversation, 'queued')
        expect(queued).not.toBeNull()
        expect(queued!.request_id).toMatch(/^[0-9a-f-]+$/)
        expect(queued!.approval_url).not.toBeUndefined()
        expect(queued!.approver_hint).not.toBeUndefined()
        expect(session!.trigger_metadata).toEqual({ kind: 'chat', supported_client_tools: ['connect_mcp'] })
    })

    // ─────────────────────────────────────────────────────────────
    // Case 9 — per-session open-approvals cap (spec.limits.max_open_approvals).
    // Distinct-args gated calls past the cap must NOT queue (args-hash dedupe
    // only collapses identical calls); the model gets a synthetic
    // approval_budget_exhausted error and the turn continues.
    // ─────────────────────────────────────────────────────────────
    it('case 9: gated calls past max_open_approvals return budget-exhausted, not a new row', async () => {
        c.setScript([
            fauxToolUse([
                fauxToolCall('@posthog/query', { project_id: 1, query: 'first — queues' }),
                fauxToolCall('@posthog/query', { project_id: 1, query: 'second — over budget' }),
            ]),
            fauxText('cap done'),
        ])
        const { application } = await c.deployAgent({
            slug: 'gated-9',
            spec: {
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/query',
                        requires_approval: true,
                        approval_policy: { allow_edit: false },
                    },
                ],
                limits: { max_open_approvals: 1 },
            },
        })
        const run = await request(c.ingress).post('/agents/gated-9/run').send({ message: 'flood' })
        await c.drain()

        // Exactly one row queued — the second call was capped, not written.
        const rows = await listApprovals(application.id, 'queued')
        expect(rows).toHaveLength(1)

        const session = await c.queue.get(run.body.session_id)
        expect(findApproval(session!.conversation, 'queued')).not.toBeNull()
        const exhausted = session!.conversation.filter((m) => {
            const cast = m as { role: string; content?: unknown }
            return (
                cast.role === 'toolResult' && JSON.stringify(cast.content ?? '').includes('approval_budget_exhausted')
            )
        })
        expect(exhausted).toHaveLength(1)
    })
})
