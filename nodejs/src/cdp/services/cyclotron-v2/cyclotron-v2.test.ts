import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2Janitor } from './janitor'
import { CyclotronV2Manager } from './manager'
import { CyclotronV2DequeuedJob, CyclotronV2JobInit } from './types'
import { CyclotronV2Worker } from './worker'

const DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const QUEUE = 'test-queue'

// ── Helpers ──────────────────────────────────────────────────────────

let assertPool: Pool

function createManager(overrides?: Record<string, unknown>): CyclotronV2Manager {
    return new CyclotronV2Manager({
        pool: { dbUrl: DB_URL },
        depthLimit: 1_000_000,
        depthCheckIntervalMs: 0, // always re-check in tests
        ...overrides,
    })
}

function createWorker(queueName = QUEUE, overrides?: Record<string, unknown>): CyclotronV2Worker {
    return new CyclotronV2Worker({
        pool: { dbUrl: DB_URL },
        queueName,
        batchMaxSize: 100,
        pollDelayMs: 10,
        includeEmptyBatches: true,
        ...overrides,
    })
}

function createJanitor(overrides?: Record<string, unknown>): CyclotronV2Janitor {
    return new CyclotronV2Janitor({
        pool: { dbUrl: DB_URL },
        cleanupGraceMs: 0,
        stallTimeoutMs: 0,
        maxTouchCount: 2,
        ...overrides,
    })
}

interface RawJobRow {
    id: string
    team_id: number
    function_id: string | null
    queue_name: string
    status: string
    priority: number
    scheduled: string | Date
    created: string | Date
    lock_id: string | null
    last_heartbeat: string | Date | null
    janitor_touch_count: number
    transition_count: number
    last_transition: string | Date
    parent_run_id: string | null
    state: Buffer | null
    distinct_id: string | null
    person_id: string | null
    action_id: string | null
}

async function queryJob(id: string): Promise<RawJobRow> {
    const res = await assertPool.query<RawJobRow>('SELECT * FROM cyclotron_jobs WHERE id = $1', [id])
    expect(res.rows).toHaveLength(1)
    return res.rows[0]
}

async function countByStatus(status: string): Promise<number> {
    const res = await assertPool.query('SELECT COUNT(*)::int AS c FROM cyclotron_jobs WHERE status = $1', [status])
    return res.rows[0].c
}

async function totalJobCount(): Promise<number> {
    const res = await assertPool.query('SELECT COUNT(*)::int AS c FROM cyclotron_jobs')
    return res.rows[0].c
}

/**
 * Connects a worker, waits for the first non-empty batch (or gives up after timeoutMs),
 * stops consuming, and returns the collected jobs.
 *
 * Uses stopConsuming() instead of disconnect() so the pool stays alive for ack calls.
 * stopConsuming() is called *outside* the callback to avoid a deadlock:
 * it awaits the consumer loop which is awaiting the callback.
 */
async function dequeueOneBatch(worker: CyclotronV2Worker, timeoutMs = 2000): Promise<CyclotronV2DequeuedJob[]> {
    let captured: CyclotronV2DequeuedJob[] = []

    await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => resolve(), timeoutMs)

        worker
            // eslint-disable-next-line @typescript-eslint/require-await
            .connect(async (batch) => {
                if (batch.length > 0 && captured.length === 0) {
                    clearTimeout(timer)
                    captured = batch
                    resolve()
                }
            })
            .catch(reject)
    })

    await worker.stopConsuming()
    return captured
}

// ── Tests ────────────────────────────────────────────────────────────

describe('Cyclotron V2', () => {
    jest.setTimeout(3000)
    // Declared here, assigned in beforeAll
    let manager: CyclotronV2Manager

    beforeAll(async () => {
        assertPool = new Pool({ connectionString: DB_URL })
        manager = createManager()
        await manager.connect()
    })

    afterAll(async () => {
        await manager.disconnect()
        await assertPool.end()
    })

    beforeEach(async () => {
        await assertPool.query('DELETE FROM cyclotron_jobs')
    })

    async function seedAndDequeue(
        jobInit?: Partial<CyclotronV2JobInit>
    ): Promise<{ id: string; job: CyclotronV2DequeuedJob }> {
        const id = await manager.createJob({ teamId: 1, queueName: QUEUE, ...jobInit })
        const worker = createWorker()
        const jobs = await dequeueOneBatch(worker)
        return { id, job: jobs[0] }
    }

    // ── Manager ──────────────────────────────────────────────────────

    describe('Manager', () => {
        it('createJob inserts with correct defaults', async () => {
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            const row = await queryJob(id)

            expect(row.status).toBe('available')
            expect(row.priority).toBe(0)
            expect(row.lock_id).toBeNull()
            expect(row.last_heartbeat).toBeNull()
            expect(row.janitor_touch_count).toBe(0)
            expect(row.transition_count).toBe(0)
            expect(row.team_id).toBe(1)
            expect(row.queue_name).toBe(QUEUE)
        })

        it('createJob with explicit id uses that id', async () => {
            const explicit = uuidv7()
            const id = await manager.createJob({ id: explicit, teamId: 1, queueName: QUEUE })
            expect(id).toBe(explicit)
            await queryJob(explicit)
        })

        it('createJob stores state, functionId, and parentRunId', async () => {
            const state = Buffer.from(JSON.stringify({ hello: 'world' }))
            const functionId = uuidv7()
            const id = await manager.createJob({
                teamId: 2,
                queueName: QUEUE,
                functionId,
                parentRunId: 'run-123',
                state,
            })
            const row = await queryJob(id)
            expect(row.function_id).toBe(functionId)
            expect(row.parent_run_id).toBe('run-123')
            expect(row.state).toEqual(state)
        })

        it('bulkCreateJobs inserts all rows', async () => {
            const jobs = Array.from({ length: 5 }, () => ({ teamId: 1, queueName: QUEUE }))
            const ids = await manager.bulkCreateJobs(jobs)
            expect(ids).toHaveLength(5)
            expect(await totalJobCount()).toBe(5)
        })

        it('bulkCreateJobs with empty array is a no-op', async () => {
            const ids = await manager.bulkCreateJobs([])
            expect(ids).toHaveLength(0)
            expect(await totalJobCount()).toBe(0)
        })

        // [columnName, initKey, sampleValueFactory]
        const lookupColumns: Array<[keyof RawJobRow, keyof CyclotronV2JobInit, () => string]> = [
            ['distinct_id', 'distinctId', () => 'user-42'],
            ['person_id', 'personId', () => uuidv7()],
            ['action_id', 'actionId', () => 'action-7'],
        ]

        it.each(lookupColumns)('createJob persists %s when provided', async (column, initKey, factory) => {
            const value = factory()
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE, [initKey]: value })
            const row = await queryJob(id)
            expect(row[column]).toBe(value)
        })

        it.each(lookupColumns)('createJob defaults %s to null when omitted', async (column) => {
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            const row = await queryJob(id)
            expect(row[column]).toBeNull()
        })

        it.each(lookupColumns)('bulkCreateJobs persists %s per row', async (column, initKey, factory) => {
            const a = factory()
            const b = factory()
            const ids = await manager.bulkCreateJobs([
                { teamId: 1, queueName: QUEUE, [initKey]: a },
                { teamId: 1, queueName: QUEUE, [initKey]: b },
                { teamId: 1, queueName: QUEUE },
            ])
            expect(ids).toHaveLength(3)
            const rows = await assertPool.query<RawJobRow>(
                `SELECT id, ${column} FROM cyclotron_jobs WHERE id = ANY($1::uuid[]) ORDER BY id`,
                [ids]
            )
            const byId = new Map(rows.rows.map((r) => [r.id, r[column]]))
            expect(byId.get(ids[0])).toBe(a)
            expect(byId.get(ids[1])).toBe(b)
            expect(byId.get(ids[2])).toBeNull()
        })

        // Only distinct_id and person_id are indexed; action_id intentionally is not.
        const indexedLookupColumns = lookupColumns.filter(([col]) => col !== 'action_id')

        it.each(indexedLookupColumns)(
            'partial index supports lookup by (team_id, %s)',
            async (column, initKey, factory) => {
                const shared = factory()
                await manager.createJob({ teamId: 1, queueName: QUEUE, [initKey]: shared })
                await manager.createJob({ teamId: 1, queueName: QUEUE, [initKey]: shared })
                await manager.createJob({ teamId: 2, queueName: QUEUE, [initKey]: shared })
                await manager.createJob({ teamId: 1, queueName: QUEUE })

                const res = await assertPool.query<{ count: string }>(
                    `SELECT COUNT(*) AS count FROM cyclotron_jobs WHERE team_id = $1 AND ${column} = $2`,
                    [1, shared]
                )
                expect(Number(res.rows[0].count)).toBe(2)
            }
        )

        it('backpressure throws when queue depth exceeds limit', async () => {
            const smallManager = createManager({ depthLimit: 2, depthCheckIntervalMs: 0 })
            await smallManager.connect()
            try {
                await smallManager.createJob({ teamId: 1, queueName: QUEUE })
                await smallManager.createJob({ teamId: 1, queueName: QUEUE })
                await expect(smallManager.createJob({ teamId: 1, queueName: QUEUE })).rejects.toThrow(/queue is full/i)
            } finally {
                await smallManager.disconnect()
            }
        })

        it('createJob rejects non-UUID personId before reaching the database', async () => {
            await expect(manager.createJob({ teamId: 1, queueName: QUEUE, personId: 'not-a-uuid' })).rejects.toThrow(
                /uuid/i
            )
        })

        it('bulkCreateJobs rejects non-UUID values without writing any rows', async () => {
            const before = await totalJobCount()
            await expect(
                manager.bulkCreateJobs([
                    { teamId: 1, queueName: QUEUE, personId: uuidv7() },
                    { teamId: 1, queueName: QUEUE, personId: 'bad-uuid' as any },
                ])
            ).rejects.toThrow(/uuid/i)
            expect(await totalJobCount()).toBe(before)
        })
    })

    // ── Worker ───────────────────────────────────────────────────────

    describe('Worker', () => {
        it('dequeues available jobs', async () => {
            await manager.createJob({ teamId: 1, queueName: QUEUE })
            await manager.createJob({ teamId: 1, queueName: QUEUE })

            const worker = createWorker()
            const jobs = await dequeueOneBatch(worker)
            expect(jobs).toHaveLength(2)
            expect(await countByStatus('running')).toBe(2)
        })

        it('respects priority ordering (lower number = higher priority)', async () => {
            await manager.createJob({ teamId: 1, queueName: QUEUE, priority: 2 })
            await manager.createJob({ teamId: 1, queueName: QUEUE, priority: 0 })
            await manager.createJob({ teamId: 1, queueName: QUEUE, priority: 1 })

            const worker = createWorker()
            const jobs = await dequeueOneBatch(worker)

            expect(jobs.map((j) => j.priority)).toEqual([0, 1, 2])
        })

        it('skips future-scheduled jobs', async () => {
            const future = new Date(Date.now() + 60_000)
            await manager.createJob({ teamId: 1, queueName: QUEUE, scheduled: future })
            await manager.createJob({ teamId: 1, queueName: QUEUE })

            const worker = createWorker()
            const jobs = await dequeueOneBatch(worker)

            expect(jobs).toHaveLength(1)
            // The future job should still be available
            expect(await countByStatus('available')).toBe(1)
        })

        it('only dequeues from the configured queue', async () => {
            await manager.createJob({ teamId: 1, queueName: 'other-queue' })
            await manager.createJob({ teamId: 1, queueName: QUEUE })

            const worker = createWorker()
            const jobs = await dequeueOneBatch(worker)

            expect(jobs).toHaveLength(1)
            expect(jobs[0].queueName).toBe(QUEUE)
        })

        it.each([
            ['ack', 'completed'],
            ['fail', 'failed'],
            ['cancel', 'canceled'],
        ] as const)('%s() sets status to %s', async (method, expectedStatus) => {
            const { id, job } = await seedAndDequeue()

            await job[method]()

            const row = await queryJob(id)
            expect(row.status).toBe(expectedStatus)
            expect(row.lock_id).toBeNull()
            expect(row.last_heartbeat).toBeNull()
        })

        it('reschedule() returns job to available', async () => {
            const { id, job } = await seedAndDequeue()
            await job.reschedule()

            const row = await queryJob(id)
            expect(row.status).toBe('available')
            expect(row.lock_id).toBeNull()
            expect(row.transition_count).toBe(2) // dequeue + reschedule
        })

        it('reschedule({ scheduledAt }) schedules into the future', async () => {
            const { id, job } = await seedAndDequeue()

            const futureDate = new Date(Date.now() + 60_000)
            await job.reschedule({ scheduledAt: futureDate })

            const row = await queryJob(id)
            expect(row.status).toBe('available')
            expect(new Date(row.scheduled).getTime()).toBeGreaterThanOrEqual(futureDate.getTime() - 1000)
            expect(new Date(row.scheduled).getTime()).toBeLessThanOrEqual(futureDate.getTime() + 1000)
        })

        it('reschedule({ state }) updates state blob', async () => {
            const { id, job } = await seedAndDequeue({ state: Buffer.from('old') })

            const newState = Buffer.from('new-state')
            await job.reschedule({ state: newState })

            const row = await queryJob(id)
            expect(row.state).toEqual(newState)
        })

        it('reschedule({ state: null }) clears state', async () => {
            const { id, job } = await seedAndDequeue({ state: Buffer.from('existing') })
            await job.reschedule({ state: null })

            const row = await queryJob(id)
            expect(row.state).toBeNull()
        })

        it('reschedule({ actionId }) updates action_id column', async () => {
            const { id, job } = await seedAndDequeue({ actionId: 'step-a' })
            await job.reschedule({ actionId: 'step-b' })

            const row = await queryJob(id)
            expect(row.action_id).toBe('step-b')
        })

        it('reschedule({ actionId: null }) clears action_id', async () => {
            const { id, job } = await seedAndDequeue({ actionId: 'step-a' })
            await job.reschedule({ actionId: null })

            const row = await queryJob(id)
            expect(row.action_id).toBeNull()
        })

        it('reschedule() without actionId leaves action_id unchanged', async () => {
            const { id, job } = await seedAndDequeue({ actionId: 'step-a' })
            await job.reschedule({ state: Buffer.from('new-state') })

            const row = await queryJob(id)
            expect(row.action_id).toBe('step-a')
        })

        it('dequeued job exposes distinctId, personId, and actionId', async () => {
            const personId = uuidv7()
            const { job } = await seedAndDequeue({
                distinctId: 'd-on-job',
                personId,
                actionId: 'a-on-job',
            })
            expect(job.distinctId).toBe('d-on-job')
            expect(job.personId).toBe(personId)
            expect(job.actionId).toBe('a-on-job')
        })

        it('reschedule rejects non-UUID personId before reaching the database', async () => {
            const { job } = await seedAndDequeue()
            await expect(job.reschedule({ personId: 'bad-uuid' as any })).rejects.toThrow(/uuid/i)
        })

        it('reschedule({ distinctId }) updates distinct_id column', async () => {
            const { id, job } = await seedAndDequeue({ distinctId: 'd-old' })
            await job.reschedule({ distinctId: 'd-new' })

            const row = await queryJob(id)
            expect(row.distinct_id).toBe('d-new')
        })

        it('reschedule({ distinctId: null }) clears distinct_id', async () => {
            const { id, job } = await seedAndDequeue({ distinctId: 'd-old' })
            await job.reschedule({ distinctId: null })

            const row = await queryJob(id)
            expect(row.distinct_id).toBeNull()
        })

        it('reschedule({ personId }) updates person_id column', async () => {
            const original = uuidv7()
            const next = uuidv7()
            const { id, job } = await seedAndDequeue({ personId: original })
            await job.reschedule({ personId: next })

            const row = await queryJob(id)
            expect(row.person_id).toBe(next)
        })

        it('reschedule({ personId: null }) clears person_id', async () => {
            const { id, job } = await seedAndDequeue({ personId: uuidv7() })
            await job.reschedule({ personId: null })

            const row = await queryJob(id)
            expect(row.person_id).toBeNull()
        })

        it('reschedule() without identifiers leaves them unchanged', async () => {
            const original = uuidv7()
            const { id, job } = await seedAndDequeue({ distinctId: 'd-keep', personId: original })
            await job.reschedule({ state: Buffer.from('new-state') })

            const row = await queryJob(id)
            expect(row.distinct_id).toBe('d-keep')
            expect(row.person_id).toBe(original)
        })

        it('heartbeat() extends last_heartbeat', async () => {
            const { id, job } = await seedAndDequeue()

            const rowBefore = await queryJob(id)
            await new Promise((r) => setTimeout(r, 50))
            await job.heartbeat()

            const rowAfter = await queryJob(id)
            expect(new Date(rowAfter.last_heartbeat!).getTime()).toBeGreaterThanOrEqual(
                new Date(rowBefore.last_heartbeat!).getTime()
            )
            expect(rowAfter.status).toBe('running')
        })

        it('double-release throws on second ack method call', async () => {
            const { job } = await seedAndDequeue()

            await job.ack()
            await expect(job.fail()).rejects.toThrow(/already released/)
            await expect(job.reschedule()).rejects.toThrow(/already released/)
            await expect(job.cancel()).rejects.toThrow(/already released/)
            await expect(job.heartbeat()).rejects.toThrow(/already released/)
        })

        it('concurrent workers get disjoint batches', async () => {
            for (let i = 0; i < 10; i++) {
                await manager.createJob({ teamId: 1, queueName: QUEUE })
            }

            const worker1 = createWorker(QUEUE, { batchMaxSize: 5 })
            const worker2 = createWorker(QUEUE, { batchMaxSize: 5 })

            const [batch1, batch2] = await Promise.all([dequeueOneBatch(worker1), dequeueOneBatch(worker2)])

            const allIds = [...batch1.map((j) => j.id), ...batch2.map((j) => j.id)]
            expect(allIds).toHaveLength(10)
            expect(new Set(allIds).size).toBe(10)
        })

        it('transition_count increments on dequeue', async () => {
            const { id, job } = await seedAndDequeue()

            expect(job.transitionCount).toBe(1)
            const row = await queryJob(id)
            expect(row.transition_count).toBe(1)
        })
    })

    // ── Janitor ──────────────────────────────────────────────────────

    describe('Janitor', () => {
        async function insertRawJob(overrides: Partial<RawJobRow> & { id: string }): Promise<void> {
            const defaults = {
                team_id: 1,
                function_id: null,
                queue_name: QUEUE,
                status: 'available',
                priority: 0,
                scheduled: new Date(),
                created: new Date(),
                lock_id: null,
                last_heartbeat: null,
                janitor_touch_count: 0,
                transition_count: 0,
                last_transition: new Date(),
                parent_run_id: null,
                state: null,
            }
            const row = { ...defaults, ...overrides }
            await assertPool.query(
                `INSERT INTO cyclotron_jobs
                 (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                  lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
                  parent_run_id, state)
                 VALUES ($1, $2, $3, $4, $5::CyclotronJobStatus, $6, $7, $8,
                         $9, $10, $11, $12, $13, $14, $15)`,
                [
                    row.id,
                    row.team_id,
                    row.function_id,
                    row.queue_name,
                    row.status,
                    row.priority,
                    row.scheduled,
                    row.created,
                    row.lock_id,
                    row.last_heartbeat,
                    row.janitor_touch_count,
                    row.transition_count,
                    row.last_transition,
                    row.parent_run_id,
                    row.state,
                ]
            )
        }

        it('cleanupTerminalJobs deletes completed/failed/canceled jobs past grace period', async () => {
            const old = new Date(Date.now() - 60_000)
            await insertRawJob({ id: uuidv7(), status: 'completed', last_transition: old })
            await insertRawJob({ id: uuidv7(), status: 'failed', last_transition: old })
            await insertRawJob({ id: uuidv7(), status: 'canceled', last_transition: old })
            // available job should survive
            await insertRawJob({ id: uuidv7(), status: 'available', last_transition: old })

            const janitor = createJanitor({ cleanupGraceMs: 0 })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.deleted).toBe(3)
            expect(await totalJobCount()).toBe(1)
            expect(await countByStatus('available')).toBe(1)
        })

        it('cleanupTerminalJobs respects grace period', async () => {
            const recent = new Date() // just now
            await insertRawJob({ id: uuidv7(), status: 'completed', last_transition: recent })

            const janitor = createJanitor({ cleanupGraceMs: 60_000 })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.deleted).toBe(0)
            expect(await totalJobCount()).toBe(1)
        })

        it('resetStalledJobs returns stalled running jobs to available', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 0,
            })

            const janitor = createJanitor({ stallTimeoutMs: 1_000 })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.stalled).toBe(1)
            const row = await queryJob(jobId)
            expect(row.status).toBe('available')
            expect(row.lock_id).toBeNull()
            expect(row.janitor_touch_count).toBe(1)
        })

        it('failPoisonPills fails jobs exceeding maxTouchCount', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 3,
            })

            const janitor = createJanitor({ stallTimeoutMs: 1_000, maxTouchCount: 2 })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.poisoned).toBe(1)
            const row = await queryJob(jobId)
            expect(row.status).toBe('failed')
        })

        it('poison pills are failed before stalled jobs are reset', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)

            // This job has been touched enough times to be a poison pill
            const poisonId = uuidv7()
            await insertRawJob({
                id: poisonId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 5,
            })

            // This job is just stalled (first time)
            const stalledId = uuidv7()
            await insertRawJob({
                id: stalledId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 0,
            })

            const janitor = createJanitor({ stallTimeoutMs: 1_000, maxTouchCount: 2 })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.poisoned).toBe(1)
            expect(result.stalled).toBe(1)

            const poison = await queryJob(poisonId)
            expect(poison.status).toBe('failed')

            const stalled = await queryJob(stalledId)
            expect(stalled.status).toBe('available')
        })

        it('measureQueueDepths returns correct counts per queue', async () => {
            await insertRawJob({ id: uuidv7(), queue_name: 'queue-a', status: 'available' })
            await insertRawJob({ id: uuidv7(), queue_name: 'queue-a', status: 'available' })
            await insertRawJob({ id: uuidv7(), queue_name: 'queue-b', status: 'available' })
            // Running jobs should not be counted
            await insertRawJob({
                id: uuidv7(),
                queue_name: 'queue-a',
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: new Date(),
            })

            // High stall timeout so the running job is NOT reset to available
            const janitor = createJanitor({ stallTimeoutMs: 60_000 })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.depths.get('queue-a')).toBe(2)
            expect(result.depths.get('queue-b')).toBe(1)
        })
    })
})
