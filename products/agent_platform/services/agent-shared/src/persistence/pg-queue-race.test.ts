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

    /** Seed one queued session and return its id. */
    async function seedSession(): Promise<string> {
        const revisions = new PgRevisionStore(pool)
        const app = await revisions.createApplication({ team_id: 1, slug: 'race', name: 'Race', description: '' })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'test/x' }),
        })
        const id = randomUUID()
        await queue.enqueue({
            id,
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
            usage_total: { ...EMPTY_USAGE_TOTAL },
            acl: [],
            pending_elevation_requests: [],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
        })
        return id
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
        const id = await seedSession()

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
        const id = await seedSession()
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
})
