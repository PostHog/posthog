import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2Janitor } from './janitor'
import { CyclotronV2Manager } from './manager'
import { CyclotronV2BatchLimit, CyclotronV2DequeuedJob, CyclotronV2JobInit } from './types'
import { CyclotronV2Worker } from './worker'
import { CyclotronV2RateLimitedWorker } from './worker-rate-limited'

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

        it('createJob accepts a non-UUID personId (column is TEXT)', async () => {
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE, personId: 'group-key-not-a-uuid' })
            const row = await queryJob(id)
            expect(row.person_id).toBe('group-key-not-a-uuid')
        })

        it('bulkCreateJobs accepts mixed UUID and non-UUID personIds', async () => {
            const validPersonId = uuidv7()
            const ids = await manager.bulkCreateJobs([
                { teamId: 1, queueName: QUEUE, personId: validPersonId },
                { teamId: 1, queueName: QUEUE, personId: 'group-key-not-a-uuid' },
            ])
            expect(ids).toHaveLength(2)
            const rows = await Promise.all(ids.map(queryJob))
            expect(rows[0].person_id).toBe(validPersonId)
            expect(rows[1].person_id).toBe('group-key-not-a-uuid')
        })

        describe('overwriteExisting (rerun re-enqueue)', () => {
            it('createJob with overwriteExisting=true refuses to clobber an in-flight (running) row', async () => {
                const id = uuidv7()
                await manager.createJob({ id, teamId: 1, queueName: QUEUE })
                // Dequeue → row is now 'running'.
                const worker = createWorker()
                const jobs = await dequeueOneBatch(worker)
                expect(jobs).toHaveLength(1)
                expect((await queryJob(id)).status).toBe('running')

                const { CyclotronJobConflictError } = await import('./manager.js')
                await expect(
                    manager.createJob({
                        id,
                        teamId: 1,
                        queueName: QUEUE,
                        overwriteExisting: true,
                    })
                ).rejects.toBeInstanceOf(CyclotronJobConflictError)

                // Existing row's status untouched.
                expect((await queryJob(id)).status).toBe('running')
            })

            it('createJob with overwriteExisting=true refuses to clobber an available (queued, not yet dequeued) row', async () => {
                const id = uuidv7()
                await manager.createJob({ id, teamId: 1, queueName: QUEUE })
                expect((await queryJob(id)).status).toBe('available')

                const { CyclotronJobConflictError } = await import('./manager.js')
                await expect(
                    manager.createJob({ id, teamId: 1, queueName: QUEUE, overwriteExisting: true })
                ).rejects.toBeInstanceOf(CyclotronJobConflictError)
            })

            it('createJob with overwriteExisting=true resets an existing terminal row to available', async () => {
                const id = uuidv7()
                // First insert + drive to terminal state via the worker.
                await manager.createJob({ id, teamId: 1, queueName: QUEUE, state: Buffer.from('v1') })
                const worker = createWorker()
                const jobs = await dequeueOneBatch(worker)
                await jobs[0].ack()
                expect((await queryJob(id)).status).toBe('completed')

                // Re-create with the same id and overwriteExisting=true — this
                // is the rerun path. The row should flip back to 'available'
                // with the new state.
                await manager.createJob({
                    id,
                    teamId: 1,
                    queueName: QUEUE,
                    state: Buffer.from('v2'),
                    overwriteExisting: true,
                })
                const row = await queryJob(id)
                expect(row.status).toBe('available')
                expect(row.state).toEqual(Buffer.from('v2'))
                expect(row.lock_id).toBeNull()
                expect(row.last_heartbeat).toBeNull()
                // transition_count bumps so the janitor's poison-pill guard
                // still has signal across reruns.
                expect(row.transition_count).toBeGreaterThan(0)
            })

            it('createJob with overwriteExisting=true on a never-seen id behaves like a normal insert', async () => {
                const id = uuidv7()
                await manager.createJob({
                    id,
                    teamId: 1,
                    queueName: QUEUE,
                    state: Buffer.from('fresh'),
                    overwriteExisting: true,
                })
                const row = await queryJob(id)
                expect(row.status).toBe('available')
                expect(row.state).toEqual(Buffer.from('fresh'))
            })

            it('bulkCreateJobs with overwriteExisting reports skipped ids via CyclotronJobConflictError when some are still active', async () => {
                const terminalId = uuidv7()
                const activeId = uuidv7()
                // Drive terminalId to completed, leave activeId in 'available'.
                await manager.bulkCreateJobs([
                    { id: terminalId, teamId: 1, queueName: QUEUE },
                    { id: activeId, teamId: 1, queueName: QUEUE },
                ])
                const worker = createWorker()
                const dequeued = await dequeueOneBatch(worker)
                const completedJob = dequeued.find((j) => j.id === terminalId)!
                await completedJob.ack()
                // The other one will still be 'running' at this point — reschedule it
                // back to 'available' so the test mirrors a more common case.
                const activeJob = dequeued.find((j) => j.id === activeId)!
                await activeJob.reschedule()
                expect((await queryJob(activeId)).status).toBe('available')

                const { CyclotronJobConflictError } = await import('./manager.js')
                await expect(
                    manager.bulkCreateJobs([
                        {
                            id: terminalId,
                            teamId: 1,
                            queueName: QUEUE,
                            overwriteExisting: true,
                            state: Buffer.from('reset'),
                        },
                        {
                            id: activeId,
                            teamId: 1,
                            queueName: QUEUE,
                            overwriteExisting: true,
                            state: Buffer.from('would-clobber'),
                        },
                    ])
                ).rejects.toBeInstanceOf(CyclotronJobConflictError)

                // The terminal one was still upserted; the active one was not.
                expect((await queryJob(terminalId)).state).toEqual(Buffer.from('reset'))
                expect((await queryJob(activeId)).state).toBeNull()
            })

            it('bulkCreateJobs with overwriteExisting flag upserts every row in the batch', async () => {
                const ids = [uuidv7(), uuidv7()]
                // Seed both as completed.
                await manager.bulkCreateJobs(ids.map((id) => ({ id, teamId: 1, queueName: QUEUE })))
                const worker = createWorker()
                const dequeued = await dequeueOneBatch(worker)
                await Promise.all(dequeued.map((j) => j.ack()))

                // Re-create both via bulk upsert.
                const resultIds = await manager.bulkCreateJobs(
                    ids.map((id) => ({
                        id,
                        teamId: 1,
                        queueName: QUEUE,
                        state: Buffer.from('rerun'),
                        overwriteExisting: true,
                    }))
                )
                expect(resultIds).toEqual(ids)
                for (const id of ids) {
                    const row = await queryJob(id)
                    expect(row.status).toBe('available')
                    expect(row.state).toEqual(Buffer.from('rerun'))
                }
            })

            it('without overwriteExisting, re-creating with the same id throws on the PK conflict', async () => {
                const id = uuidv7()
                await manager.createJob({ id, teamId: 1, queueName: QUEUE })
                await expect(manager.createJob({ id, teamId: 1, queueName: QUEUE })).rejects.toThrow(
                    /duplicate key value/i
                )
            })
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

        describe('bulkCreateAndCheckIn', () => {
            it('atomically inserts new children and reschedules self', async () => {
                const { id: parentId, job } = await seedAndDequeue()

                const newState = Buffer.from(JSON.stringify({ cursor: 'next-page', totalEnqueued: 500 }))
                const future = new Date(Date.now() + 60_000)

                const result = await job.bulkCreateAndCheckIn({
                    newJobs: [
                        { teamId: 1, queueName: 'hogflow', parentRunId: parentId },
                        { teamId: 1, queueName: 'hogflow', parentRunId: parentId },
                    ],
                    selfDisposition: { kind: 'reschedule', scheduledAt: future, state: newState },
                })

                expect(result.newJobIds).toHaveLength(2)

                // Self is back to available with new state + scheduled
                const parent = await queryJob(parentId)
                expect(parent.status).toBe('available')
                expect(parent.lock_id).toBeNull()
                expect(parent.state?.toString()).toBe(newState.toString())
                expect(new Date(parent.scheduled).getTime()).toBeCloseTo(future.getTime(), -2)

                // Children exist on their own queue
                const children = await assertPool.query(
                    `SELECT id, queue_name, status, parent_run_id FROM cyclotron_jobs
                     WHERE parent_run_id = $1 ORDER BY id`,
                    [parentId]
                )
                expect(children.rows).toHaveLength(2)
                expect(children.rows[0].queue_name).toBe('hogflow')
                expect(children.rows[0].status).toBe('available')
            })

            it('acks self atomically with child inserts', async () => {
                const { id: parentId, job } = await seedAndDequeue()

                await job.bulkCreateAndCheckIn({
                    newJobs: [{ teamId: 1, queueName: 'hogflow', parentRunId: parentId }],
                    selfDisposition: { kind: 'ack' },
                })

                const parent = await queryJob(parentId)
                expect(parent.status).toBe('completed')
                expect(parent.lock_id).toBeNull()

                expect(await countByStatus('available')).toBe(1) // child
            })

            it('fails self atomically with child inserts', async () => {
                const { id: parentId, job } = await seedAndDequeue()

                await job.bulkCreateAndCheckIn({
                    newJobs: [],
                    selfDisposition: { kind: 'fail' },
                })

                const parent = await queryJob(parentId)
                expect(parent.status).toBe('failed')
            })

            it('handles empty newJobs (terminal page with no new children)', async () => {
                const { id: parentId, job } = await seedAndDequeue()

                const result = await job.bulkCreateAndCheckIn({
                    newJobs: [],
                    selfDisposition: { kind: 'ack' },
                })

                expect(result.newJobIds).toEqual([])
                expect((await queryJob(parentId)).status).toBe('completed')
            })

            it('rolls back both writes if the insert fails (atomicity)', async () => {
                const { id: parentId, job } = await seedAndDequeue()

                // Force an insert failure by providing an invalid teamId
                // (the schema parse will reject this before we even reach SQL,
                // so the failure is pre-TX; verify self-state is untouched.)
                await expect(
                    job.bulkCreateAndCheckIn({
                        newJobs: [{ teamId: 'bad-type' as any, queueName: 'hogflow' }],
                        selfDisposition: { kind: 'reschedule' },
                    })
                ).rejects.toThrow()

                // Parent still locked / running — no partial state
                const parent = await queryJob(parentId)
                expect(parent.status).toBe('running')
                expect(parent.lock_id).not.toBeNull()
            })

            it('rolls back the self update when a child insert fails inside the TX', async () => {
                // Real DB-level rollback path (vs the Zod pre-check above): two
                // children with the same explicit id → second INSERT violates
                // the PK constraint mid-TX → the self UPDATE must roll back too.
                const { id: parentId, job } = await seedAndDequeue()
                const duplicateId = '00000000-0000-0000-0000-000000000001'

                await expect(
                    job.bulkCreateAndCheckIn({
                        newJobs: [
                            { id: duplicateId, teamId: 1, queueName: 'hogflow' },
                            { id: duplicateId, teamId: 1, queueName: 'hogflow' },
                        ],
                        selfDisposition: { kind: 'reschedule' },
                    })
                ).rejects.toThrow()

                // Self row untouched — still locked and running
                const parent = await queryJob(parentId)
                expect(parent.status).toBe('running')
                expect(parent.lock_id).not.toBeNull()

                // No children persisted
                const children = await assertPool.query(
                    `SELECT id FROM cyclotron_jobs WHERE parent_run_id IS NOT NULL OR id = $1`,
                    [duplicateId]
                )
                expect(children.rows).toHaveLength(0)
            })

            it('rolls back when the lock_id has been reassigned between dequeue and commit (janitor race)', async () => {
                // Simulates the janitor's stall-recovery: the worker holds the
                // dequeued job, but while it's mid-page the janitor decides the
                // job stalled and reassigns the lock to another worker. The
                // current TX's self UPDATE then matches zero rows because the
                // WHERE lock_id = $2 filter fails. Without a rowCount guard,
                // the child inserts would commit silently while the cursor
                // doesn't advance — up to ~500 duplicate sends per page on
                // replay by the other worker.
                const { id: parentId, job } = await seedAndDequeue()

                // Forcibly change the lock_id from underneath the worker.
                await assertPool.query(`UPDATE cyclotron_jobs SET lock_id = gen_random_uuid() WHERE id = $1`, [
                    parentId,
                ])

                await expect(
                    job.bulkCreateAndCheckIn({
                        newJobs: [{ teamId: 1, queueName: 'hogflow', parentRunId: parentId }],
                        selfDisposition: { kind: 'reschedule' },
                    })
                ).rejects.toThrow()

                // No child rows leaked through
                const children = await assertPool.query(`SELECT id FROM cyclotron_jobs WHERE parent_run_id = $1`, [
                    parentId,
                ])
                expect(children.rows).toHaveLength(0)
            })

            it('throws if the job was already released', async () => {
                const { job } = await seedAndDequeue()
                await job.ack()

                await expect(
                    job.bulkCreateAndCheckIn({
                        newJobs: [],
                        selfDisposition: { kind: 'ack' },
                    })
                ).rejects.toThrow('already released')
            })
        })

        describe('CyclotronV2RateLimitedWorker', () => {
            // The hook is consulted on every poll. It receives the number of
            // rows actually visible (capped at batchMaxSize). Returning a
            // positive limit clamps the SQL LIMIT to min(limit, batchMaxSize);
            // 0 skips the dequeue and sleeps; undefined falls back to batchMaxSize.
            const createRateLimitedWorker = (
                getBatchLimit: (requested: number) => Promise<CyclotronV2BatchLimit | undefined>,
                overrides?: Record<string, unknown>
            ): CyclotronV2RateLimitedWorker =>
                new CyclotronV2RateLimitedWorker(
                    {
                        pool: { dbUrl: DB_URL },
                        queueName: QUEUE,
                        batchMaxSize: 100,
                        pollDelayMs: 10,
                        includeEmptyBatches: true,
                        ...overrides,
                    },
                    getBatchLimit
                )

            it('clamps the batch to the granted limit', async () => {
                await manager.bulkCreateJobs(Array.from({ length: 10 }, () => ({ teamId: 1, queueName: QUEUE })))

                // eslint-disable-next-line @typescript-eslint/require-await
                const worker = createRateLimitedWorker(async () => ({ limit: 3 }))
                const jobs = await dequeueOneBatch(worker)

                expect(jobs).toHaveLength(3)
                expect(await countByStatus('available')).toBe(7)
            })

            it('skips the dequeue entirely when the granted limit is 0', async () => {
                await manager.createJob({ teamId: 1, queueName: QUEUE })
                await manager.createJob({ teamId: 1, queueName: QUEUE })

                // eslint-disable-next-line @typescript-eslint/require-await
                const worker = createRateLimitedWorker(async () => ({ limit: 0, sleepMs: 5 }), {
                    includeEmptyBatches: false,
                })
                const jobs = await dequeueOneBatch(worker, 200)

                expect(jobs).toHaveLength(0)
                // Critical: the SQL UPDATE never fires — rows stay 'available'.
                expect(await countByStatus('available')).toBe(2)
                expect(await countByStatus('running')).toBe(0)
            })

            it('falls back to batchMaxSize when the hook returns undefined', async () => {
                await manager.bulkCreateJobs(Array.from({ length: 5 }, () => ({ teamId: 1, queueName: QUEUE })))

                // eslint-disable-next-line @typescript-eslint/require-await
                const worker = createRateLimitedWorker(async () => undefined)
                const jobs = await dequeueOneBatch(worker)

                expect(jobs).toHaveLength(5)
            })

            it('exits promptly when stopConsuming is called during a throttled sleep', async () => {
                // eslint-disable-next-line @typescript-eslint/require-await
                const worker = createRateLimitedWorker(async () => ({ limit: 0, sleepMs: 100 }))

                await worker.connect(async () => {})
                // Let the loop reach the sleep branch.
                await new Promise((resolve) => setTimeout(resolve, 50))

                const stopStarted = Date.now()
                await worker.stopConsuming()
                const stopDuration = Date.now() - stopStarted

                // At most one sleepMs (100ms) + small overhead — never indefinite.
                expect(stopDuration).toBeLessThan(300)
            })

            it('keeps looping after the hook rejects', async () => {
                await manager.createJob({ teamId: 1, queueName: QUEUE })
                await manager.createJob({ teamId: 1, queueName: QUEUE })

                // Reject once, then return a valid decision so dequeueOneBatch
                // captures a non-empty batch and resolves.
                let calls = 0
                const worker = createRateLimitedWorker(() => {
                    calls += 1
                    if (calls === 1) {
                        return Promise.reject(new Error('boom'))
                    }
                    return Promise.resolve({ limit: 5 })
                })

                const jobs = await dequeueOneBatch(worker, 1000)
                expect(jobs).toHaveLength(2)
                // The first call rejected — the loop's catch swallowed it and tried again.
                expect(calls).toBeGreaterThan(1)
            })

            it('skips the limiter entirely when there is no work to dequeue', async () => {
                // Idle queue → peek returns no rows → worker sleeps without
                // ever consulting the rate limiter. Keeps the bucket at
                // capacity and the limiter's metrics silent during idle.
                let hookCalls = 0
                const worker = createRateLimitedWorker(() => {
                    hookCalls += 1
                    return Promise.resolve({ limit: 5 })
                })

                await worker.connect(async () => {})
                // Let the loop poll several times (pollDelayMs is 10ms in tests).
                await new Promise((resolve) => setTimeout(resolve, 200))
                await worker.stopConsuming()

                // Many poll cycles ran (~20 at 10ms cadence) but no jobs exist,
                // so the limiter hook is never invoked.
                expect(hookCalls).toBe(0)
            })

            it('passes the visible row count to the limiter hook', async () => {
                // Sparse-traffic regression guard. 3 ready rows + batchMaxSize=100
                // → hook must be asked for 3 tokens, not 100. Without pre-sizing,
                // a single trickle of jobs would drain the full bucket per send.
                await manager.bulkCreateJobs(Array.from({ length: 3 }, () => ({ teamId: 1, queueName: QUEUE })))

                const requestedHistory: number[] = []
                const worker = createRateLimitedWorker((requested) => {
                    requestedHistory.push(requested)
                    return Promise.resolve({ limit: requested })
                })

                await dequeueOneBatch(worker)

                // First (and only relevant) call: 3 rows visible → 3 requested.
                expect(requestedHistory[0]).toBe(3)
            })

            it('caps the visible row count at batchMaxSize', async () => {
                // Backlog of 10 rows with batchMaxSize=4 should ask for 4
                // (the batch ceiling), not 10.
                await manager.bulkCreateJobs(Array.from({ length: 10 }, () => ({ teamId: 1, queueName: QUEUE })))

                const requestedHistory: number[] = []
                const worker = createRateLimitedWorker(
                    (requested) => {
                        requestedHistory.push(requested)
                        return Promise.resolve({ limit: requested })
                    },
                    { batchMaxSize: 4 }
                )

                await dequeueOneBatch(worker)

                expect(requestedHistory[0]).toBe(4)
            })
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

        it('reschedule accepts a non-UUID personId', async () => {
            const { id, job } = await seedAndDequeue({ personId: uuidv7() })
            await job.reschedule({ personId: 'group-key-not-a-uuid' })

            const row = await queryJob(id)
            expect(row.person_id).toBe('group-key-not-a-uuid')
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

    // ── Email fair dequeue ───────────────────────────────────────────
    //
    // dequeue_seq is precomputed at insert time for email-queue jobs.
    // Sorting ascending by it interleaves tenants 1-for-1, so a single
    // email from one team isn't blocked behind another team's 2M-row
    // campaign. Counter state lives in cyclotron_email_team_seq.

    describe('Email fair dequeue', () => {
        const EMAIL_QUEUE = 'email'

        const readDequeueSeq = async (id: string): Promise<bigint | null> => {
            const res = await assertPool.query<{ dequeue_seq: string | null }>(
                'SELECT dequeue_seq FROM cyclotron_jobs WHERE id = $1',
                [id]
            )
            const raw = res.rows[0].dequeue_seq
            return raw === null ? null : BigInt(raw)
        }

        const readTeamCounter = async (teamId: number): Promise<bigint | null> => {
            const res = await assertPool.query<{ counter: string }>(
                'SELECT counter FROM cyclotron_email_team_seq WHERE team_id = $1',
                [teamId]
            )
            return res.rows.length === 0 ? null : BigInt(res.rows[0].counter)
        }

        beforeEach(async () => {
            // Wipe the per-team counter table between tests so each starts cold.
            await assertPool.query('DELETE FROM cyclotron_email_team_seq')
        })

        describe('Manager: dequeue_seq assignment', () => {
            it('assigns dequeue_seq for email jobs, NULL for other queues', async () => {
                const [emailId] = await manager.bulkCreateJobs([{ teamId: 7, queueName: EMAIL_QUEUE }])
                const [hogId] = await manager.bulkCreateJobs([{ teamId: 7, queueName: 'hog' }])

                expect(await readDequeueSeq(emailId)).not.toBeNull()
                expect(await readDequeueSeq(hogId)).toBeNull()
            })

            it('uses counter * 16M + team_id as the formula', async () => {
                const teamId = 42
                const [id] = await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])

                const seq = await readDequeueSeq(id)
                // First job for this team: counter = 1.
                // dequeue_seq = 1 * 16,777,216 + 42 = 16,777,258
                expect(seq).toBe(BigInt(16_777_216) + BigInt(teamId))
            })

            it('increments the team counter monotonically across calls', async () => {
                const teamId = 100
                await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])
                await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])
                await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])

                expect(await readTeamCounter(teamId)).toBe(3n)
            })

            it("starts a new team's counter at the existing max (Hatchet p_max_assigned)", async () => {
                // Without this, a brand-new tenant's burst would slot in at
                // counter=1 and cut ahead of every established team's
                // in-flight emails. Hatchet's pattern: first-ever insert for
                // a team starts at `MAX(counter) + 1` across the table, so
                // they line up *next to* existing teams instead of jumping
                // the queue. Subsequent emails for that team keep
                // incrementing normally.
                await manager.bulkCreateJobs([{ teamId: 1, queueName: EMAIL_QUEUE }])
                await manager.bulkCreateJobs([{ teamId: 1, queueName: EMAIL_QUEUE }])
                // Team 2's first ever email → counter = max(2) + 1 = 3, not 1.
                await manager.bulkCreateJobs([{ teamId: 2, queueName: EMAIL_QUEUE }])

                expect(await readTeamCounter(1)).toBe(2n)
                expect(await readTeamCounter(2)).toBe(3n)
            })

            it("doesn't let a new team's batch cut ahead of an established team's in-flight email", async () => {
                // The inversion scenario the Hatchet pattern is designed to fix:
                //   - Established tenant has been sending for a while → high counter.
                //   - Newcomer tenant enqueues their first big batch.
                // The established tenant's next email should still sort *before*
                // the newcomer's batch — without Hatchet, the newcomer would
                // land at counter=1 and bury every established email behind
                // their burst.
                const established = 100
                const newcomer = 200

                // Established tenant builds up a counter via prior activity.
                await manager.bulkCreateJobs(
                    Array.from({ length: 10 }, () => ({ teamId: established, queueName: EMAIL_QUEUE }))
                )
                // Established tenant's 11th email.
                const [establishedNewId] = await manager.bulkCreateJobs([
                    { teamId: established, queueName: EMAIL_QUEUE },
                ])
                // Newcomer's first-ever batch.
                await manager.bulkCreateJobs(
                    Array.from({ length: 50 }, () => ({ teamId: newcomer, queueName: EMAIL_QUEUE }))
                )

                const establishedSeq = await readDequeueSeq(establishedNewId)
                const newcomerRows = await assertPool.query<{ dequeue_seq: string }>(
                    'SELECT dequeue_seq FROM cyclotron_jobs WHERE team_id = $1 ORDER BY dequeue_seq ASC LIMIT 1',
                    [newcomer]
                )
                const newcomerMinSeq = BigInt(newcomerRows.rows[0].dequeue_seq)

                expect(establishedSeq).not.toBeNull()
                expect(establishedSeq!).toBeLessThan(newcomerMinSeq)
            })

            it('assigns sequential dequeue_seq within a bulk batch for the same team', async () => {
                const teamId = 50
                const ids = await manager.bulkCreateJobs([
                    { teamId, queueName: EMAIL_QUEUE },
                    { teamId, queueName: EMAIL_QUEUE },
                    { teamId, queueName: EMAIL_QUEUE },
                ])

                const seqs = await Promise.all(ids.map(readDequeueSeq))
                expect(seqs).toEqual([
                    BigInt(16_777_216) + BigInt(teamId), // counter=1
                    BigInt(16_777_216) * 2n + BigInt(teamId), // counter=2
                    BigInt(16_777_216) * 3n + BigInt(teamId), // counter=3
                ])
                expect(await readTeamCounter(teamId)).toBe(3n)
            })

            it('handles mixed-team bulk batches without crossing counters', async () => {
                const ids = await manager.bulkCreateJobs([
                    { teamId: 1, queueName: EMAIL_QUEUE },
                    { teamId: 2, queueName: EMAIL_QUEUE },
                    { teamId: 1, queueName: EMAIL_QUEUE },
                    { teamId: 2, queueName: EMAIL_QUEUE },
                ])
                const seqs = await Promise.all(ids.map(readDequeueSeq))
                const BLOCK = BigInt(16_777_216)

                // Team 1's two jobs use counter 1 and 2; same for team 2.
                expect(seqs[0]).toBe(BLOCK + 1n) // team 1, counter 1
                expect(seqs[1]).toBe(BLOCK + 2n) // team 2, counter 1
                expect(seqs[2]).toBe(BLOCK * 2n + 1n) // team 1, counter 2
                expect(seqs[3]).toBe(BLOCK * 2n + 2n) // team 2, counter 2
            })

            it('leaves non-email jobs in a bulk batch with NULL dequeue_seq', async () => {
                const ids = await manager.bulkCreateJobs([
                    { teamId: 1, queueName: EMAIL_QUEUE },
                    { teamId: 1, queueName: 'hog' },
                    { teamId: 1, queueName: EMAIL_QUEUE },
                ])

                const seqs = await Promise.all(ids.map(readDequeueSeq))
                expect(seqs[0]).not.toBeNull() // email
                expect(seqs[1]).toBeNull() // hog
                expect(seqs[2]).not.toBeNull() // email
                // Only the email jobs bumped the team counter.
                expect(await readTeamCounter(1)).toBe(2n)
            })
        })

        describe('Worker: fairDequeue ordering', () => {
            // The email queue is intrinsically fair-dequeued — the worker derives
            // it from the queue name, so an EMAIL_QUEUE worker is already fair.
            const createFairWorker = (overrides?: Record<string, unknown>): CyclotronV2Worker =>
                createWorker(EMAIL_QUEUE, overrides)

            it('picks small-tenant jobs into the same batch as big-tenant jobs', async () => {
                // The 2M-vs-1 scenario at a smaller scale: team A enqueues 5,
                // team B enqueues 1. With strict FIFO, B's 1 sits behind A's 5.
                // With fair dequeue, B's 1 is in the very first batch of 2.
                //
                // Both teams in a single bulkCreateJobs call — this mirrors
                // the prod path where cdp-events-consumer batches emails from
                // many teams into one INSERT.
                const teamA = 100
                const teamB = 200
                await manager.bulkCreateJobs([
                    ...Array.from({ length: 5 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE })),
                    { teamId: teamB, queueName: EMAIL_QUEUE },
                ])

                const worker = createFairWorker({ batchMaxSize: 2 })
                const jobs = await dequeueOneBatch(worker)

                expect(jobs).toHaveLength(2)
                expect(new Set(jobs.map((j) => j.teamId))).toEqual(new Set([teamA, teamB]))
            })

            it('interleaves three teams across multiple rounds', async () => {
                // Mixed-volume scenario:
                //   team A enqueues 20 emails, team B enqueues 10, team C enqueues 1.
                //
                // All three teams in a single bulkCreateJobs call — mirrors
                // the prod path (cdp-events-consumer batches multi-team emails
                // into one INSERT). Dequeue one row at a time so each call's
                // pick is deterministic (lowest dequeue_seq remaining).
                const teamA = 100
                const teamB = 200
                const teamC = 300
                await manager.bulkCreateJobs([
                    ...Array.from({ length: 20 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE })),
                    ...Array.from({ length: 10 }, () => ({ teamId: teamB, queueName: EMAIL_QUEUE })),
                    { teamId: teamC, queueName: EMAIL_QUEUE },
                ])

                const drained: number[] = []
                for (let i = 0; i < 31; i++) {
                    const worker = createFairWorker({ batchMaxSize: 1 })
                    const batch = await dequeueOneBatch(worker)
                    expect(batch).toHaveLength(1)
                    drained.push(batch[0].teamId)
                    await batch[0].ack()
                }

                // Expected: A,B,C (round 1) / A,B (rounds 2-10) / A...A (rounds 11-20).
                // Within a round, team_id ASC breaks ties (A=100 < B=200 < C=300).
                const expected: number[] = []
                for (let round = 1; round <= 10; round++) {
                    expected.push(teamA, teamB)
                    if (round === 1) {
                        expected.push(teamC)
                    }
                }
                for (let round = 11; round <= 20; round++) {
                    expected.push(teamA)
                }
                expect(drained).toEqual(expected)
            })

            it('keeps interleaving across waves once both teams are established', async () => {
                // Per-team counters don't reset across enqueue calls — once
                // a team has any history, later waves continue from where
                // they left off and interleave with other established teams.
                //
                // We pre-establish both teams with a single multi-team batch
                // (matches the prod cdp-events-consumer pattern), then run
                // subsequent waves for each team separately to prove the
                // round-robin survives wave boundaries:
                //
                //   Pre-establish: A, A, A, B, B, B (one batch) → A,B counter 1..3 each
                //   Wave 2:        B, B             (separate)  → B counter 4, 5
                //   Wave 3:        A, A             (separate)  → A counter 4, 5
                //
                // Dequeue order: A1,B1, A2,B2, A3,B3, A4,B4, A5,B5.
                const teamA = 100
                const teamB = 200
                await manager.bulkCreateJobs([
                    ...Array.from({ length: 3 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE })),
                    ...Array.from({ length: 3 }, () => ({ teamId: teamB, queueName: EMAIL_QUEUE })),
                ])
                await manager.bulkCreateJobs(
                    Array.from({ length: 2 }, () => ({ teamId: teamB, queueName: EMAIL_QUEUE }))
                )
                await manager.bulkCreateJobs(
                    Array.from({ length: 2 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE }))
                )

                const drained: number[] = []
                for (let i = 0; i < 10; i++) {
                    const worker = createFairWorker({ batchMaxSize: 1 })
                    const batch = await dequeueOneBatch(worker)
                    expect(batch).toHaveLength(1)
                    drained.push(batch[0].teamId)
                    await batch[0].ack()
                }

                expect(drained).toEqual([teamA, teamB, teamA, teamB, teamA, teamB, teamA, teamB, teamA, teamB])
            })

            it('drains every team in the first multi-team batch even with skewed volumes', async () => {
                // 10/5/2 distribution drained in batches of 3. We don't assert
                // the within-batch order (UPDATE...RETURNING doesn't preserve
                // the CTE's ORDER BY), only that the *composition* of each
                // batch is what the algorithm guarantees: the lowest-counter
                // rows across all teams, regardless of who has more backlog.
                //
                // All three teams in one bulkCreateJobs call — matches the
                // prod path (cdp-events-consumer batches multi-team emails).
                const teamA = 100
                const teamB = 200
                const teamC = 300
                await manager.bulkCreateJobs([
                    ...Array.from({ length: 10 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE })),
                    ...Array.from({ length: 5 }, () => ({ teamId: teamB, queueName: EMAIL_QUEUE })),
                    ...Array.from({ length: 2 }, () => ({ teamId: teamC, queueName: EMAIL_QUEUE })),
                ])

                const batches: number[][] = []
                for (let i = 0; i < 6; i++) {
                    const worker = createFairWorker({ batchMaxSize: 3 })
                    const batch = await dequeueOneBatch(worker)
                    if (batch.length === 0) {
                        break
                    }
                    batches.push(batch.map((j) => j.teamId))
                    for (const job of batch) {
                        await job.ack()
                    }
                }

                const countsByTeam = (batch: number[]): Record<number, number> => {
                    const out: Record<number, number> = {}
                    for (const teamId of batch) {
                        out[teamId] = (out[teamId] ?? 0) + 1
                    }
                    return out
                }

                // Global dequeue_seq order is:
                //   A1,B1,C1 | A2,B2,C2 | A3,B3,A4 | B4,A5,B5 | A6,A7,A8 | A9,A10
                expect(batches.map(countsByTeam)).toEqual([
                    { [teamA]: 1, [teamB]: 1, [teamC]: 1 },
                    { [teamA]: 1, [teamB]: 1, [teamC]: 1 },
                    { [teamA]: 2, [teamB]: 1 },
                    { [teamA]: 1, [teamB]: 2 },
                    { [teamA]: 3 },
                    { [teamA]: 2 },
                ])
            })

            it('keeps non-email queues on FIFO (priority, scheduled) ordering', async () => {
                // Fair dequeue is intrinsic to the email queue; a non-email
                // queue worker stays strict FIFO. Team A enqueues 5 then team B
                // enqueues 1 on the default (hog) queue — A's 5 come first.
                const teamA = 100
                const teamB = 200
                await manager.bulkCreateJobs(Array.from({ length: 5 }, () => ({ teamId: teamA, queueName: QUEUE })))
                await manager.bulkCreateJobs([{ teamId: teamB, queueName: QUEUE }])

                const worker = createWorker(QUEUE, { batchMaxSize: 2 })
                const jobs = await dequeueOneBatch(worker)

                expect(jobs).toHaveLength(2)
                expect(jobs.every((j) => j.teamId === teamA)).toBe(true)
            })

            it('drains legacy rows (NULL dequeue_seq) before new ones when fair is on', async () => {
                // Simulate a row inserted before the migration ran: NULL dequeue_seq.
                // NULLS FIRST in the ORDER BY means it should be picked up before
                // the new fair-ordered row.
                const teamId = 1
                const [newerId, legacyId] = await manager.bulkCreateJobs([
                    { teamId, queueName: EMAIL_QUEUE },
                    { teamId, queueName: EMAIL_QUEUE },
                ])
                // Backdate one row by manually clearing its dequeue_seq to mimic
                // a pre-migration row.
                await assertPool.query('UPDATE cyclotron_jobs SET dequeue_seq = NULL WHERE id = $1', [legacyId])

                const worker = createFairWorker({ batchMaxSize: 1 })
                const jobs = await dequeueOneBatch(worker)

                expect(jobs).toHaveLength(1)
                expect(jobs[0].id).toBe(legacyId)
                expect(newerId).toBeDefined() // (silences unused-var warning)
            })

            it('assigns dequeue_seq when a hog job is rescheduled into the email queue', async () => {
                // Hogflow → email re-routing is the most common path into the
                // email queue in production: a workflow step calls
                // `job.reschedule({ queueName: 'email' })`. Without dequeue_seq
                // assignment on that path, the row lands with NULL and the
                // NULLS FIRST sort would drain it ahead of fair-ordered rows
                // — bypassing the per-team interleave entirely.
                const teamId = 42
                const hogJobId = await manager.createJob({ teamId, queueName: 'hog' })

                // Dequeue the hog job (mimics what the hog worker does), then
                // reschedule it into the email queue (mimics the hog → email
                // routing in hog-executor.service.ts).
                const hogWorker = createWorker('hog')
                const [hogJob] = await dequeueOneBatch(hogWorker)
                expect(hogJob.id).toBe(hogJobId)
                await hogJob.reschedule({ queueName: EMAIL_QUEUE })

                // The row should now have a dequeue_seq matching the formula
                // and the per-team counter should have been bumped to 1.
                expect(await readDequeueSeq(hogJobId)).toBe(BigInt(16_777_216) + BigInt(teamId))
                expect(await readTeamCounter(teamId)).toBe(1n)
            })

            it('does not bump dequeue_seq when an email job is rescheduled within the email queue', async () => {
                // Retry / failure recovery path: an email job that's already
                // on the email queue gets rescheduled back to 'available' with
                // queueName='email' should *keep* its existing dequeue_seq so
                // it doesn't lose its place in the round-robin. Bumping the
                // counter on every retry would silently demote retried jobs.
                const teamId = 99
                const [id] = await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])
                const seqBefore = await readDequeueSeq(id)
                expect(seqBefore).not.toBeNull()

                const worker = createFairWorker({ batchMaxSize: 1 })
                const [job] = await dequeueOneBatch(worker)
                await job.reschedule({ queueName: EMAIL_QUEUE })

                expect(await readDequeueSeq(id)).toBe(seqBefore)
                // Counter stays at 1 — no new claim happened.
                expect(await readTeamCounter(teamId)).toBe(1n)
            })
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
