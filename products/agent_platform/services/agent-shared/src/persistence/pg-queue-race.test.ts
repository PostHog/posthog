/**
 * Real-PG races between a mid-run `/send` requeue and the worker that still
 * holds the session. The claim's FOR UPDATE lock is released at claim-commit,
 * not held for the run, so these interleavings are only guarded by the SQL
 * predicates under test:
 *
 *   1. double-claim — `/send` on a `running` session must not flip it to
 *      `queued`, or a second worker claims it and two loops interleave
 *      writes on one conversation.
 *   2. lost wakeup — a `/send` that lands after the running worker's last
 *      `drainPendingInputs` must survive the worker's final state write;
 *      an unconditional `state='completed'` strands the pending input on a
 *      session nothing will ever claim.
 *
 * Same harness as pg-impls.test.ts: real Postgres, schema reset per test,
 * suite skipped when the local dev-stack DB is unreachable.
 */

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

import { isReachable, reset } from '@posthog/agent-shared/testing'

import { AgentSpecSchema, EMPTY_USAGE_TOTAL } from '../spec/spec'
import { applyApprovalDecision } from './approval-decision'
import { PgApprovalStore } from './pg-approval-store'
import { PgSessionQueue } from './pg-queue'
import { PgRevisionStore } from './pg-revision-store'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

const maybeDescribe = process.env.SKIP_PG_TESTS === '1' ? describe.skip : describe

maybeDescribe('PgSessionQueue requeue-vs-running races (real PG)', () => {
    let pool: Pool
    let reachable = false
    let queue: PgSessionQueue

    beforeAll(async () => {
        reachable = await isReachable(TEST_DB_URL)
        if (!reachable) {
            // eslint-disable-next-line no-console
            console.warn(`[pg-queue-race.test] ${TEST_DB_URL} unreachable — skipping`)
            return
        }
        pool = new Pool({ connectionString: TEST_DB_URL, max: 4 })
    })

    beforeEach(async () => {
        if (!reachable) {
            return
        }
        await reset({ databaseUrl: TEST_DB_URL })
        queue = new PgSessionQueue(pool)
    })

    afterAll(async () => {
        if (pool) {
            await pool.end()
        }
    })

    /** Enqueue one queued session under an existing app/revision. */
    async function enqueueUnder(appId: string, revId: string, externalKey: string | null = null): Promise<string> {
        const id = randomUUID()
        await queue.enqueue({
            id,
            application_id: appId,
            revision_id: revId,
            team_id: 1,
            external_key: externalKey,
            idempotency_key: null,
            trigger_metadata: null,
            state: 'queued',
            conversation: [{ role: 'user', content: 'hi', timestamp: Date.now() }],
            pending_inputs: [],
            principal: null,
            retry_count: 0,
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })
        return id
    }

    /** Seed one queued session; returns its id plus the app/revision ids. */
    async function seedSession(slug = 'race'): Promise<{ id: string; appId: string; revId: string }> {
        const revisions = new PgRevisionStore(pool)
        const app = await revisions.createApplication({ team_id: 1, slug, name: 'Race', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'test/x' }),
        })
        const id = await enqueueUnder(app.id, rev.id)
        return { id, appId: app.id, revId: rev.id }
    }

    /** What ingress does on `/send` (chat.ts sendHandler) and `/run`-resume (enqueue.ts). */
    async function simulateSend(sessionId: string, content: string): Promise<void> {
        await queue.appendPendingInput(sessionId, { role: 'user', content, timestamp: Date.now() })
        await queue.requeueForInput(sessionId)
    }

    it('a /send against a running session must not make it claimable by a second worker', async () => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()

        // Worker A claims; its claim transaction commits, so the row lock is gone.
        const a = await queue.claim(500)
        expect(a?.id).toBe(id)
        expect(a?.state).toBe('running')

        // /send lands mid-run.
        await simulateSend(id, 'steering message')

        // Worker B polls. The session is still being run by A — B must not get it.
        const b = await queue.claim(300)
        expect(b).toBeNull()

        // The running worker keeps ownership; the input waits in pending_inputs
        // for A's next drainPendingInputs.
        const row = await queue.get(id)
        expect(row?.state).toBe('running')
        expect(row?.pending_inputs).toHaveLength(1)
    })

    it('worker finalize must not strand a pending input that arrived after the last drain', async () => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()
        const a = await queue.claim(500)
        expect(a?.id).toBe(id)

        // Worker A drained pending_inputs for its last turn already…
        await queue.drainPendingInputs(id)
        // …then /send lands in the gap before A's final state write.
        await simulateSend(id, 'follow-up the worker never saw')

        // Worker A finishes and persists its outcome (worker.ts runOne
        // final write for a completed run).
        const persisted = await queue.finalizeRun(id, {
            state: 'completed',
            conversation: a!.conversation,
            usage_total: a!.usage_total,
        })

        // The undrained input must leave the session claimable — otherwise it
        // sits on a `completed` row until the janitor closes it 24h later.
        expect(persisted).toBe('queued')
        const row = await queue.get(id)
        expect(row?.pending_inputs).toHaveLength(1)
        expect(row?.state).toBe('queued')

        // And a sibling worker actually picks it up.
        const b = await queue.claim(300)
        expect(b?.id).toBe(id)
    })

    // chat.ts documents `cancelled`/`failed` as always-terminal (410) and
    // `closed` as terminal-unless-allow_restart. A wake that read the state
    // BEFORE termination landed used to flip the row back to `queued`
    // (resurrection); the guard must hold under that interleaving: the append
    // stays in pending_inputs, the state stays terminal, nothing claims it.
    it.each(['cancelled', 'closed', 'failed'] as const)(
        'a wake racing termination must not resurrect a %s session',
        async (terminal) => {
            if (!reachable) {
                return
            }
            const { id } = await seedSession()
            // Ingress read the session pre-termination (state check passed)…
            await queue.update(id, { state: terminal })
            // …then its append + wake land after the terminal write.
            await simulateSend(id, 'raced-in message')

            const row = await queue.get(id)
            expect(row?.state).toBe(terminal)
            expect(row?.pending_inputs).toHaveLength(1)
            expect(await queue.claim(200)).toBeNull()
        }
    )

    it.each([
        ['closed', 'queued'],
        ['cancelled', 'cancelled'],
        ['failed', 'failed'],
    ] as const)('allowRestartFromClosed reopens only closed sessions: %s → %s', async (from, expected) => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()
        await queue.update(id, { state: from })
        await queue.appendPendingInput(id, { role: 'user', content: 'restart', timestamp: Date.now() })
        await queue.requeueForInput(id, { allowRestartFromClosed: true })
        expect((await queue.get(id))?.state).toBe(expected)
    })

    it('sweep closeIfIdle must not clobber a session re-queued since the candidate read', async () => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()
        await queue.update(id, { state: 'completed' })
        // The janitor read this row as an idle-completed candidate, then a
        // /send re-queued it before the janitor's close write.
        await simulateSend(id, 'follow-up')
        expect(await queue.closeIfIdle(id)).toBeNull()
        const row = await queue.get(id)
        expect(row?.state).toBe('queued')
        expect((await queue.claim(300))?.id).toBe(id)
    })

    it('closeIfIdle re-queues instead of closing when an undrained input landed', async () => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()
        await queue.update(id, { state: 'completed' })
        // The append landed but its requeueForInput hasn't run yet — closing
        // now would strand the input behind a terminal state.
        await queue.appendPendingInput(id, { role: 'user', content: 'not yet requeued', timestamp: Date.now() })
        expect(await queue.closeIfIdle(id)).toBe('queued')
        expect((await queue.claim(300))?.id).toBe(id)
    })

    // The runner reopens a cancelled session ONLY when its outcome is
    // `completed` (the documented cancel-reopen: the runner catches the cancel,
    // persists the partial reply, reopens). Every other outcome on a cancelled
    // row must leave it cancelled — in particular a shutdown-suspend (`queued`)
    // that raced the cancel used to resurrect the session into the claim pool.
    it.each(['queued', 'closed', 'failed'] as const)(
        'finalize with outcome %s racing a cancel leaves the session cancelled',
        async (outcome) => {
            if (!reachable) {
                return
            }
            const { id } = await seedSession()
            const a = await queue.claim(500)
            expect(a?.id).toBe(id)
            // Ingress lands the durable cancel mid-run…
            await queue.update(id, { state: 'cancelled' })
            // …then the worker finalizes without having seen it (queued = a
            // pod-shutdown suspend; closed/failed = the loop's own outcome).
            const persisted = await queue.finalizeRun(id, {
                state: outcome,
                conversation: a!.conversation,
                usage_total: a!.usage_total,
            })
            expect(persisted).toBe('cancelled')
            expect((await queue.get(id))?.state).toBe('cancelled')
            expect(await queue.claim(200)).toBeNull()
        }
    )

    // The cancel-reopen itself must keep both guarantees: with no undrained
    // input it reopens as `completed` (the runner's documented overwrite of
    // ingress's durable cancel), and with an undrained input it re-queues —
    // the reopen path used to skip the completed-with-pending-inputs rescue
    // and strand the input on the reopened row.
    it('cancel-reopen with an undrained input re-queues instead of stranding it', async () => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()
        const a = await queue.claim(500)
        expect(a?.id).toBe(id)
        await queue.update(id, { state: 'cancelled' })
        // A /send (or approval envelope) landed after the run's last drain.
        await queue.appendPendingInput(id, { role: 'user', content: 'raced past the cancel', timestamp: Date.now() })
        const persisted = await queue.finalizeRun(id, {
            state: 'completed',
            conversation: a!.conversation,
            usage_total: a!.usage_total,
        })
        expect(persisted).toBe('queued')
        expect((await queue.claim(300))?.id).toBe(id)
    })

    it('cancel-reopen with no pending input still reopens as completed', async () => {
        if (!reachable) {
            return
        }
        const { id } = await seedSession()
        const a = await queue.claim(500)
        expect(a?.id).toBe(id)
        await queue.update(id, { state: 'cancelled' })
        const persisted = await queue.finalizeRun(id, {
            state: 'completed',
            conversation: a!.conversation,
            usage_total: a!.usage_total,
        })
        expect(persisted).toBe('completed')
        expect((await queue.get(id))?.state).toBe('completed')
    })

    // Terminal rows still take inert `pending_inputs` appends (a raced /send),
    // and the append bumps `updated_at` — so recency alone would let a dead
    // session shadow a live one under the same external key, breaking resume.
    it('findByExternalKey prefers a live session over a terminal one with a fresher updated_at', async () => {
        if (!reachable) {
            return
        }
        const { appId, revId } = await seedSession()
        const live = await enqueueUnder(appId, revId, 'thread-1')
        const dead = await enqueueUnder(appId, revId, 'thread-1')
        await queue.update(dead, { state: 'cancelled' })
        // Inert append on the terminal row — lands in pending_inputs and
        // bumps updated_at past the live row's.
        await queue.appendPendingInput(dead, { role: 'user', content: 'raced-in', timestamp: Date.now() })

        expect((await queue.findByExternalKey(appId, 'thread-1', revId))?.id).toBe(live)
    })

    /** Queue one approval row for the session; returns the request. */
    async function seedApproval(
        approvals: PgApprovalStore,
        ids: { id: string; appId: string; revId: string }
    ): Promise<{ id: string }> {
        const { request } = await approvals.upsertQueued({
            id: randomUUID(),
            session_id: ids.id,
            application_id: ids.appId,
            team_id: 1,
            revision_id: ids.revId,
            turn: 1,
            tool_call_id: 'tc-1',
            tool_name: '@posthog/team-delete',
            proposed_args: { team_id: 1 },
            assistant_message: { role: 'assistant', content: [{ type: 'text', text: '' }], timestamp: 0 },
            approver_scope: { type: 'principal', allow_edit: false },
            expires_at: new Date(Date.now() + 60_000).toISOString(),
        })
        return request
    }

    // Wiring + semantics for the approval-decision wake against real PG: the
    // decision path used to write `update({state:'queued'})` unconditionally,
    // which could hand a running session to a second worker. The decision must
    // still succeed (the approval row flips) while the session stays running —
    // the live worker drains the marker at its next turn.
    it('a late approval decision does not change a running session state', async () => {
        if (!reachable) {
            return
        }
        const ids = await seedSession()
        expect((await queue.claim(500))?.id).toBe(ids.id)
        const approvals = new PgApprovalStore(pool)
        const request = await seedApproval(approvals, ids)

        const result = await applyApprovalDecision(
            { approvals, queue },
            {
                requestId: request.id,
                applicationId: ids.appId,
                decision: 'approve',
                // decision_by is a uuid column in PG.
                decidedBy: randomUUID(),
            }
        )
        expect(result.ok).toBe(true)

        const row = await queue.get(ids.id)
        expect(row?.state).toBe('running')
        expect(row?.pending_inputs).toHaveLength(1)
        expect(await queue.claim(200)).toBeNull()
    })

    // A decision on a session that already terminated must fail closed: the
    // old path left an immortal 'approving' row plus an inert decided marker
    // in pending_inputs, and a later legitimate allow_restart restart drained
    // the marker — dispatching a stale approved tool call from a dead turn.
    // Now the approval row expires and no marker lands.
    it.each(['cancelled', 'closed', 'failed'] as const)(
        'a late approval decision on a %s session expires the approval and appends no marker',
        async (terminal) => {
            if (!reachable) {
                return
            }
            const ids = await seedSession()
            const approvals = new PgApprovalStore(pool)
            const request = await seedApproval(approvals, ids)
            await queue.update(ids.id, { state: terminal })

            const result = await applyApprovalDecision(
                { approvals, queue },
                { requestId: request.id, applicationId: ids.appId, decision: 'approve', decidedBy: randomUUID() }
            )
            expect(result.ok).toBe(false)
            if (!result.ok) {
                expect(result.error).toBe('session_terminal')
            }
            expect((await approvals.get(request.id))?.state).toBe('expired')

            const row = await queue.get(ids.id)
            expect(row?.state).toBe(terminal)
            expect(row?.pending_inputs).toHaveLength(0)
            expect(await queue.claim(200)).toBeNull()
        }
    )
})
