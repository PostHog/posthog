/**
 * Approval-gated tools: real e2e contract for v0.
 *
 * Pins the wire-level behaviour for approval-gated tools. The seven cases below
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

import { AuthProvider, publicVerifier, readBearer } from '@posthog/agent-ingress'

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
                      approval_policy: { allow_edit: !!opts.allowEdit },
                  }
                : {
                      kind: 'native' as const,
                      id: opts.toolId,
                      requires_approval: true,
                      approval_policy: { allow_edit: !!opts.allowEdit },
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
        expect(queued!.approver_hint).toMatch(/admin/i)

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
                    args: { type: 'object', properties: { ping: { type: 'string' } } },
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
    // Case 8 — posthog-code client suppresses URL prose.
    // Same flow as case 1 but the caller sets X-PostHog-Client: posthog-code,
    // so the queued envelope must NOT carry approval_url / approver_hint —
    // the desktop chat preview renders an in-line approval card and the
    // standalone console (port 3040) is going away.
    // ─────────────────────────────────────────────────────────────
    it('case 8: posthog-code client omits approval_url + approver_hint from the queued envelope', async () => {
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
            .set('X-PostHog-Client', 'posthog-code')
            .send({ message: 'go' })
        expect(run.status).toBe(200)
        await c.drain()

        const session = await c.queue.get(run.body.session_id)
        const queued = findApproval(session!.conversation, 'queued')
        expect(queued).not.toBeNull()
        // The model still sees the request_id + state so it knows the call
        // is gated, but neither the URL nor the admin hint — its only
        // option is to acknowledge the queued state in plain text.
        expect(queued!.request_id).toMatch(/^[0-9a-f-]+$/)
        expect(queued!.approval_url).toBeUndefined()
        expect(queued!.approver_hint).toBeUndefined()
        // Sanity: client_kind landed on the session row.
        expect(session!.trigger_metadata).toMatchObject({ client_kind: 'posthog-code' })
    })
})

// ─────────────────────────────────────────────────────────────────────
// Per-asker authorisation shortcut (#23 step 3).
//
// The dispatcher reads the most recent user-turn's `sender` and, if it
// satisfies the tool's `approver_scope`, dispatches directly instead of
// queueing for someone else to approve. Verifies the load-bearing demo
// scenario: regular user → queues; admin user → dispatches.
//
// The harness doesn't carry a real posthog_organizationmembership table,
// so we stub `isAskerInApproverScope` to "is the sender id the
// admin PAT?". The dispatcher's real production code reads through the
// identity store + posthog DB; that path is covered by
// per-asker-auth.test.ts.
//
// We use PAT-based chat auth (rather than slack) because the chat
// trigger stamps a `service`-kind sender carrying the pat_id verbatim
// — easy to recognise — whereas the slack identity store mints
// non-deterministic UUIDs.
// ─────────────────────────────────────────────────────────────────────
describe('approval-gated tools: per-asker shortcut (#23 step 3)', () => {
    const ADMIN_PAT_ID = 'pat-admin'
    const NORMAL_PAT_ID = 'pat-normal'

    const authProvider: AuthProvider = {
        verifiers: [
            publicVerifier,
            {
                modeType: 'posthog',
                async verify(req, _mode, application) {
                    const bearer = readBearer(req)
                    if (!bearer) {
                        return { ok: false, status: 0, reason: 'skip' }
                    }
                    const userId =
                        bearer === 'admin-token' ? ADMIN_PAT_ID : bearer === 'normal-token' ? NORMAL_PAT_ID : null
                    if (!userId) {
                        return { ok: false, status: 401, reason: 'invalid_token' }
                    }
                    return {
                        ok: true,
                        principal: {
                            kind: 'posthog',
                            user_id: userId,
                            team_id: application.team_id,
                        },
                        credentials: { posthog_api: { kind: 'posthog_bearer', token: bearer } },
                    }
                },
            },
        ],
    }

    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster({
            authProvider,
            // Stub the per-asker check to recognise the admin PAT id. The real
            // production check resolves principal → AgentUser → posthog_user
            // → OrganizationMembership level; the harness short-circuits all
            // of that with a literal id match.
            isAskerInApproverScope: async (conversation, _teamId, approverScope) => {
                if (!approverScope.includes('team_admins')) {
                    return false
                }
                for (let i = conversation.length - 1; i >= 0; i--) {
                    const m = conversation[i] as {
                        role: string
                        sender?: { kind?: string; user_id?: string }
                    }
                    if (m.role !== 'user') {
                        continue
                    }
                    if (m.sender?.kind === 'posthog' && m.sender.user_id === ADMIN_PAT_ID) {
                        return true
                    }
                    if (m.sender) {
                        return false
                    }
                }
                return false
            },
        })
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    async function listQueuedApprovals(applicationId: string): Promise<Array<{ id: string }>> {
        const res = await request(c.janitor).get('/approvals').query({ application_id: applicationId, state: 'queued' })
        expect(res.status).toBe(200)
        return res.body.results as Array<{ id: string }>
    }

    it('non-admin: gated call queues an approval (B.2 v0 behaviour preserved)', async () => {
        c.setScript([
            fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }),
            fauxText('queued for approval'),
        ])
        const { application } = await c.deployAgent({
            slug: 'shortcut-noadmin',
            spec: {
                auth: { modes: [{ type: 'posthog' }] },
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/query',
                        requires_approval: true,
                        approval_policy: { allow_edit: false },
                    },
                ],
            },
        })

        await request(c.ingress)
            .post('/agents/shortcut-noadmin/run')
            .set('authorization', 'Bearer normal-token')
            .send({ message: 'delete the cohort' })
        await c.drain()

        const queued = await listQueuedApprovals(application.id)
        expect(queued).toHaveLength(1)
    })

    it('admin: gated call dispatches directly, NO approval row, model sees real tool result', async () => {
        c.setScript([fauxCallTool('@posthog/query', { project_id: 1, query: 'select 1' }), fauxText('done')])
        const { application } = await c.deployAgent({
            slug: 'shortcut-admin',
            spec: {
                auth: { modes: [{ type: 'posthog' }] },
                tools: [
                    {
                        kind: 'native',
                        id: '@posthog/query',
                        requires_approval: true,
                        approval_policy: { allow_edit: false },
                    },
                ],
            },
        })

        const run = await request(c.ingress)
            .post('/agents/shortcut-admin/run')
            .set('authorization', 'Bearer admin-token')
            .send({ message: 'delete the cohort' })
        await c.drain()

        // No approval row written — the dispatcher took the shortcut.
        const queued = await listQueuedApprovals(application.id)
        expect(queued).toHaveLength(0)

        // The conversation carries a real @posthog/query toolResult, not
        // a synthetic queued envelope. The harness's PostHog internal
        // client echoes `{ rows: [{query}], columns: ['query'] }`.
        const session = await c.queue.get(run.body.session_id)
        const toolResults = session!.conversation.filter((m) => (m as { role: string }).role === 'toolResult')
        expect(toolResults).toHaveLength(1)
        const result = toolResults[0] as { content: Array<{ type: string; text: string }>; toolName: string }
        expect(result.toolName).toBe('@posthog/query')
        expect(result.content[0].text).toContain('rows')
        expect(result.content[0].text).not.toContain('queued')
    })
})
