import { Client, Pool } from 'pg'
import { Histogram, register } from 'prom-client'
import { v7 as uuidv7 } from 'uuid'

import { HOG_INVOCATION_RESULTS_OUTPUT } from '~/common/outputs'
import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { parseJSON } from '~/common/utils/json-parse'
import { sleep } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'

import {
    HOGFLOW_BATCH_RESOLVE_QUEUE,
    deserializeResolverState,
    serializeResolverState,
} from '../hogflows/batch-resolver.types'
import {
    HogInvocationResultRow,
    HogInvocationResultsService,
    HogInvocationResultsServiceOutput,
} from '../monitoring/hog-invocation-results.service'
import { FAIR_DEQUEUE_CANDIDATE_CAP } from './due-rows-sql'
import { CyclotronV2Janitor, JANITOR_POISON_PILL_ERROR_KIND } from './janitor'
import { CyclotronV2Manager } from './manager'
import { createCyclotronPool } from './pg-pool'
import {
    CYCLOTRON_COUNTER_MAX,
    CYCLOTRON_TRANSITION_CHURN_THRESHOLD,
    CyclotronV2BatchLimit,
    CyclotronV2CleanupResult,
    CyclotronV2DequeuedJob,
    CyclotronV2IdempotentJobInit,
    CyclotronV2JobInit,
} from './types'
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
        boundedPolls: true,
        boundedFairDequeue: true,
        ...overrides,
    })
}

function createMockResults(ok = true): {
    service: HogInvocationResultsService
    recordTerminalFailureDurably: jest.Mock
} {
    const recordTerminalFailureDurably = jest.fn().mockResolvedValue(ok)
    return {
        service: { recordTerminalFailureDurably } as unknown as HogInvocationResultsService,
        recordTerminalFailureDurably,
    }
}

class InMemoryResultsTopic extends IngestionOutputs<HogInvocationResultsServiceOutput> {
    readonly rows: { output: string; row: HogInvocationResultRow }[] = []

    constructor() {
        super({} as Record<HogInvocationResultsServiceOutput, IngestionOutput>)
    }

    override produce(output: HogInvocationResultsServiceOutput, message: IngestionOutputMessage): Promise<void> {
        this.rows.push({ output, row: parseJSON(message.value!.toString('utf-8')) as HogInvocationResultRow })
        return Promise.resolve()
    }
}

function createJanitor(overrides?: Record<string, unknown>, results?: HogInvocationResultsService): CyclotronV2Janitor {
    return new CyclotronV2Janitor(
        {
            pool: { dbUrl: DB_URL },
            cleanupGraceMs: 0,
            stallTimeoutMs: 0,
            maxTouchCount: 2,
            // Off by default so existing reset tests keep immediate-retry semantics;
            // the backoff tests opt in explicitly.
            stallBackoffBaseMs: 0,
            ...overrides,
        },
        results
    )
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
    cancel_requested_at: string | Date | null
    dequeue_seq: string | null
    pending_wake: Record<string, unknown> | null
}

async function queryJob(id: string): Promise<RawJobRow> {
    const res = await assertPool.query<RawJobRow>('SELECT * FROM cyclotron_jobs WHERE id = $1', [id])
    expect(res.rows).toHaveLength(1)
    return res.rows[0]
}

// Compares in the database: `scheduled` and Date.now() are different clocks and skew.
async function jobIsDue(id: string): Promise<boolean> {
    const res = await assertPool.query<{ due: boolean }>(
        'SELECT scheduled <= now() AS due FROM cyclotron_jobs WHERE id = $1',
        [id]
    )
    expect(res.rows).toHaveLength(1)
    return res.rows[0].due
}

async function makeHeartbeatStale(id: string): Promise<void> {
    await assertPool.query(`UPDATE cyclotron_jobs SET last_heartbeat = NOW() - INTERVAL '1 minute' WHERE id = $1`, [id])
}

async function heartbeatIsFresh(id: string): Promise<boolean> {
    const res = await assertPool.query<{ fresh: boolean }>(
        `SELECT last_heartbeat > NOW() - INTERVAL '10 seconds' AS fresh FROM cyclotron_jobs WHERE id = $1`,
        [id]
    )
    return res.rows[0].fresh
}

async function settlesWithin(work: Promise<unknown>, guardMs: number): Promise<boolean> {
    let guard: NodeJS.Timeout | undefined
    const guardElapsed = new Promise<false>((resolve) => {
        guard = setTimeout(() => resolve(false), guardMs)
    })
    try {
        return await Promise.race([work.then(() => true), guardElapsed])
    } finally {
        clearTimeout(guard)
    }
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

async function backendsWaitingOnLocks(): Promise<number> {
    const { rows } = await assertPool.query<{ n: number }>(
        `SELECT COUNT(*)::int AS n FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'`
    )
    return rows[0].n
}

async function backendsNamed(applicationName: string): Promise<number> {
    const { rows } = await assertPool.query<{ n: number }>(
        'SELECT COUNT(*)::int AS n FROM pg_stat_activity WHERE application_name = $1',
        [applicationName]
    )
    return rows[0].n
}

// ── Tests ────────────────────────────────────────────────────────────

async function gaugeValueForQueue(queue: string, metricName = 'cdp_cyclotron_v2_queue_depth'): Promise<number | null> {
    const metric = await register.getSingleMetricAsString(metricName)
    const line = metric.split('\n').find((l) => l.includes(`queue="${queue}"`))
    return line ? Number(line.trim().split(' ').pop()) : null
}

// Absent until the queue's first churning dequeue, so a missing line reads as 0.
async function loopErrorCountForQueue(queue: string): Promise<number> {
    const metric = await register.getSingleMetricAsString('cdp_cyclotron_v2_consumer_loop_errors_total')
    const line = metric.split('\n').find((l) => l.includes(`queue="${queue}"`))
    return line ? Number(line.trim().split(' ').pop()) : 0
}

async function pollCountForQueue(queue: string, outcome: string): Promise<number> {
    const metric = await register.getSingleMetricAsString('cdp_cyclotron_v2_polls_total')
    const line = metric.split('\n').find((l) => l.includes(`queue="${queue}"`) && l.includes(`outcome="${outcome}"`))
    return line ? Number(line.trim().split(' ').pop()) : 0
}

function useFakeClockWithRealIo(): void {
    jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask', 'performance'] })
}

async function waitForWorkerToSettle(what: string, condition: () => Promise<boolean>): Promise<void> {
    const deadline = performance.now() + 2_000
    while (!(await condition())) {
        if (performance.now() > deadline) {
            throw new Error(`timed out waiting for ${what}`)
        }
        await new Promise((resolve) => setImmediate(resolve))
    }
    await new Promise((resolve) => setImmediate(resolve))
}

async function emptyPollIntervals(
    worker: CyclotronV2Worker,
    queue: string,
    intervals: number,
    afterEmptyPoll: (pollNumber: number) => Promise<unknown> = () => Promise.resolve()
): Promise<number[]> {
    return pollIntervals(worker, () => pollCountForQueue(queue, 'empty'), intervals, afterEmptyPoll)
}

async function pollIntervals(
    worker: CyclotronV2Worker,
    polls: () => Promise<number>,
    intervals: number,
    afterPoll: (pollNumber: number) => Promise<unknown> = () => Promise.resolve()
): Promise<number[]> {
    const pollsBefore = await polls()
    const pollTimes: number[] = []
    useFakeClockWithRealIo()
    try {
        await worker.connect(async () => {})
        while (pollTimes.length <= intervals) {
            if (pollTimes.length > 0) {
                jest.advanceTimersToNextTimer()
            }
            const pollNumber = pollTimes.length + 1
            await waitForWorkerToSettle(`poll ${pollNumber}`, async () => (await polls()) - pollsBefore >= pollNumber)
            pollTimes.push(Date.now())
            await afterPoll(pollNumber)
        }
    } finally {
        await worker.disconnect()
        jest.useRealTimers()
    }
    return pollTimes.slice(1).map((time, i) => time - pollTimes[i])
}

async function holdDueJobLocked(manager: CyclotronV2Manager, queue: string): Promise<() => Promise<void>> {
    const id = await manager.createJob({ teamId: 1, queueName: queue })
    const client = await assertPool.connect()
    await client.query('BEGIN')
    await client.query('SELECT id FROM cyclotron_jobs WHERE id = $1 FOR UPDATE', [id])
    return async () => {
        await client.query('ROLLBACK')
        client.release()
    }
}

async function churnCountForQueue(queue: string): Promise<number> {
    const metric = await register.getSingleMetricAsString('cdp_cyclotron_v2_high_transition_dequeues')
    const line = metric.split('\n').find((l) => l.includes(`queue="${queue}"`))
    return line ? Number(line.trim().split(' ').pop()) : 0
}

const ENQUEUE_PHASE_METRIC = 'cdp_cyclotron_v2_enqueue_phase_duration_seconds'

async function enqueuePhaseCounts(): Promise<Record<string, number>> {
    const metric = register.getSingleMetric(ENQUEUE_PHASE_METRIC) as Histogram | undefined
    const values = metric ? (await metric.get()).values : []
    return Object.fromEntries(
        values
            .filter((v) => v.metricName === `${ENQUEUE_PHASE_METRIC}_count`)
            .map((v) => [`${v.labels.caller}:${v.labels.phase}`, v.value])
    )
}

async function managerSequenceReserveTotals(): Promise<{ count: number; seconds: number }> {
    const metric = register.getSingleMetric(ENQUEUE_PHASE_METRIC) as Histogram | undefined
    const values = metric ? (await metric.get()).values : []
    const sample = (suffix: 'count' | 'sum'): number =>
        values.find(
            (v) =>
                v.metricName === `${ENQUEUE_PHASE_METRIC}_${suffix}` &&
                v.labels.caller === 'manager' &&
                v.labels.phase === 'sequence_reserve'
        )?.value ?? 0
    return { count: sample('count'), seconds: sample('sum') }
}

async function enqueuePhaseCountsDuring(step: () => Promise<unknown>): Promise<Record<string, number>> {
    const before = await enqueuePhaseCounts()
    await step()
    const after = await enqueuePhaseCounts()
    return Object.fromEntries(
        Object.entries(after)
            .map(([key, count]) => [key, count - (before[key] ?? 0)])
            .filter(([, delta]) => delta !== 0)
    )
}

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

        it('countInFlightJobs counts available and running jobs grouped by action', async () => {
            const functionId = uuidv7()
            const otherFunctionId = uuidv7()
            await manager.createJob({ teamId: 1, queueName: QUEUE, functionId, actionId: 'delay_1' })
            const runningId = await manager.createJob({ teamId: 1, queueName: QUEUE, functionId, actionId: 'delay_1' })
            await assertPool.query(`UPDATE cyclotron_jobs SET status = 'running' WHERE id = $1`, [runningId])
            // No actionId: a job written before the lookup column existed → position unknown
            await manager.createJob({ teamId: 1, queueName: QUEUE, functionId })
            // Not counted: terminal status, other function, other team
            const completedId = await manager.createJob({ teamId: 1, queueName: QUEUE, functionId })
            await assertPool.query(`UPDATE cyclotron_jobs SET status = 'completed' WHERE id = $1`, [completedId])
            await manager.createJob({ teamId: 1, queueName: QUEUE, functionId: otherFunctionId, actionId: 'delay_1' })
            await manager.createJob({ teamId: 2, queueName: QUEUE, functionId, actionId: 'delay_1' })

            expect(await manager.countInFlightJobs(1, functionId)).toEqual({
                count: 3,
                byAction: { delay_1: 2 },
                positionUnknown: 1,
            })
        })

        describe('rescheduleParkedJobs', () => {
            const FAR_FUTURE = () => new Date(Date.now() + 7 * 24 * 3600 * 1000)

            async function seedParked(
                functionId: string,
                over?: Partial<CyclotronV2JobInit> & { scheduled?: Date }
            ): Promise<string> {
                return await manager.createJob({
                    teamId: 1,
                    queueName: QUEUE,
                    functionId,
                    actionId: 'delay_1',
                    scheduled: FAR_FUTURE(),
                    ...over,
                })
            }

            it('sweeps only matching parked rows into the window, regardless of queue', async () => {
                const functionId = uuidv7()
                const before = Date.now()
                const sweptId = await seedParked(functionId)
                const emailQueueId = await seedParked(functionId, { queueName: 'email' })
                const otherActionId = await seedParked(functionId, { actionId: 'message_1' })
                const otherFunctionId = await seedParked(uuidv7())
                const otherTeamId = await seedParked(functionId, { teamId: 2 })
                const runningId = await seedParked(functionId)
                await assertPool.query(`UPDATE cyclotron_jobs SET status = 'running' WHERE id = $1`, [runningId])
                const wakingSoon = new Date(Date.now() + 60_000)
                const wakingSoonId = await seedParked(functionId, { scheduled: wakingSoon })

                const result = await manager.rescheduleParkedJobs({ teamId: 1, functionId, actionIds: ['delay_1'] })

                expect(result.swept).toBe(2)
                expect(result.done).toBe(true)
                // Swept rows (hogflow-queue and email-queue alike — parked waits can sit on any
                // queue) land inside [sweepFloor, sweepUntil]: never sooner than the floor, never
                // later than their original wake.
                for (const id of [sweptId, emailQueueId]) {
                    const scheduled = new Date((await queryJob(id)).scheduled).getTime()
                    expect(scheduled).toBeGreaterThanOrEqual(result.sweepFloor.getTime() - 1000)
                    expect(scheduled).toBeLessThanOrEqual(result.sweepUntil.getTime() + 1000)
                }
                expect(result.sweepFloor.getTime()).toBeGreaterThan(before)
                // Untouched: other action/function/team, running rows, rows already waking soon
                for (const id of [otherActionId, otherFunctionId, otherTeamId, runningId]) {
                    const scheduled = new Date((await queryJob(id)).scheduled).getTime()
                    expect(scheduled).toBeGreaterThan(Date.now() + 6 * 24 * 3600 * 1000)
                }
                expect(new Date((await queryJob(wakingSoonId)).scheduled).getTime()).toBe(wakingSoon.getTime())
            })

            it('is idempotent: a second call with the same bounds sweeps nothing', async () => {
                const functionId = uuidv7()
                const id = await seedParked(functionId)

                const first = await manager.rescheduleParkedJobs({ teamId: 1, functionId, actionIds: ['delay_1'] })
                expect(first.swept).toBe(1)
                const scheduledAfterFirst = new Date((await queryJob(id)).scheduled).getTime()

                const second = await manager.rescheduleParkedJobs({
                    teamId: 1,
                    functionId,
                    actionIds: ['delay_1'],
                    sweepFloor: first.sweepFloor,
                    sweepUntil: first.sweepUntil,
                })
                expect(second).toMatchObject({ swept: 0, remaining: 0, done: true })
                expect(new Date((await queryJob(id)).scheduled).getTime()).toBe(scheduledAfterFirst)
            })

            it('honors explicitly passed bounds and echoes them back', async () => {
                const functionId = uuidv7()
                const id = await seedParked(functionId)
                const sweepFloor = new Date(Date.now() + 1800_000)
                const sweepUntil = new Date(Date.now() + 3600_000)

                const result = await manager.rescheduleParkedJobs({
                    teamId: 1,
                    functionId,
                    actionIds: ['delay_1'],
                    sweepFloor,
                    sweepUntil,
                })

                expect(result.sweepFloor).toEqual(sweepFloor)
                expect(result.sweepUntil).toEqual(sweepUntil)
                const scheduled = new Date((await queryJob(id)).scheduled).getTime()
                expect(scheduled).toBeGreaterThanOrEqual(sweepFloor.getTime())
                expect(scheduled).toBeLessThanOrEqual(sweepUntil.getTime())
            })

            it('re-sizes stale bounds instead of sweeping the remainder into the past', async () => {
                const functionId = uuidv7()
                await seedParked(functionId)
                const staleFloor = new Date(Date.now() - 3600_000)
                const staleUntil = new Date(Date.now() - 1800_000)

                const result = await manager.rescheduleParkedJobs({
                    teamId: 1,
                    functionId,
                    actionIds: ['delay_1'],
                    sweepFloor: staleFloor,
                    sweepUntil: staleUntil,
                })

                expect(result.swept).toBe(1)
                expect(result.sweepFloor.getTime()).toBeGreaterThan(Date.now())
                const parked = await assertPool.query(
                    `SELECT COUNT(*)::int AS c FROM cyclotron_jobs WHERE function_id = $1 AND scheduled <= NOW()`,
                    [functionId]
                )
                expect(parked.rows[0].c).toBe(0)
            })

            it('clamps a caller-passed floor to the server floor so bounds cannot mass-wake the backlog', async () => {
                // A past floor with a still-fresh until would land the random targets in the
                // past — the floor is the sweep's safety property and is enforced server-side.
                const functionId = uuidv7()
                const id = await seedParked(functionId)

                const result = await manager.rescheduleParkedJobs({
                    teamId: 1,
                    functionId,
                    actionIds: ['delay_1'],
                    sweepFloor: new Date(Date.now() - 3600_000),
                    sweepUntil: new Date(Date.now() + 3600_000),
                })

                expect(result.swept).toBe(1)
                // Default floor is 600s: the swept row must never wake sooner than that
                const scheduled = new Date((await queryJob(id)).scheduled).getTime()
                expect(scheduled).toBeGreaterThanOrEqual(Date.now() + 600_000 - 5000)
                expect(result.sweepFloor.getTime()).toBeGreaterThanOrEqual(Date.now() + 600_000 - 5000)
            })

            it.each([
                ['count / rate inside the clamps', 30, 30],
                ['clamped up to the min window', 5, 10],
                ['clamped down to the max window', 100, 50],
            ])('sizes the window from the parked count: %s', async (_desc, jobCount, expectedWindowSeconds) => {
                const sizingManager = createManager({
                    rescheduleFloorSeconds: 60,
                    rescheduleWakeRatePerSecond: 1,
                    rescheduleMinWindowSeconds: 10,
                    rescheduleMaxWindowSeconds: 50,
                    rescheduleChunkSleepMs: 0,
                })
                await sizingManager.connect()
                try {
                    const functionId = uuidv7()
                    await sizingManager.bulkCreateJobs(
                        Array.from({ length: jobCount }, () => ({
                            teamId: 1,
                            queueName: QUEUE,
                            functionId,
                            actionId: 'delay_1',
                            scheduled: FAR_FUTURE(),
                        }))
                    )

                    const result = await sizingManager.rescheduleParkedJobs({
                        teamId: 1,
                        functionId,
                        actionIds: ['delay_1'],
                    })

                    expect(result.sweepUntil.getTime() - result.sweepFloor.getTime()).toBe(expectedWindowSeconds * 1000)
                } finally {
                    await sizingManager.disconnect()
                }
            })

            it('slices work across calls, keeping the window fixed', async () => {
                const slicingManager = createManager({
                    rescheduleChunkSize: 2,
                    rescheduleMaxChunksPerCall: 2,
                    rescheduleChunkSleepMs: 0,
                })
                await slicingManager.connect()
                try {
                    const functionId = uuidv7()
                    await slicingManager.bulkCreateJobs(
                        Array.from({ length: 5 }, () => ({
                            teamId: 1,
                            queueName: QUEUE,
                            functionId,
                            actionId: 'delay_1',
                            scheduled: FAR_FUTURE(),
                        }))
                    )

                    const first = await slicingManager.rescheduleParkedJobs({
                        teamId: 1,
                        functionId,
                        actionIds: ['delay_1'],
                    })
                    expect(first).toMatchObject({ swept: 4, remaining: 1, done: false })

                    const second = await slicingManager.rescheduleParkedJobs({
                        teamId: 1,
                        functionId,
                        actionIds: ['delay_1'],
                        sweepFloor: first.sweepFloor,
                        sweepUntil: first.sweepUntil,
                    })
                    expect(second).toMatchObject({ swept: 1, remaining: 0, done: true })
                    // sweepUntil is the idempotency bound and must stay fixed across slices;
                    // the floor legitimately drifts forward per slice (clamped to now + floor).
                    expect(second.sweepUntil).toEqual(first.sweepUntil)
                    expect(second.sweepFloor.getTime()).toBeGreaterThanOrEqual(first.sweepFloor.getTime())
                } finally {
                    await slicingManager.disconnect()
                }
            })

            it('skips rows locked by a concurrent transaction', async () => {
                const functionId = uuidv7()
                const lockedId = await seedParked(functionId)
                const freeId = await seedParked(functionId)

                const client = await assertPool.connect()
                try {
                    await client.query('BEGIN')
                    await client.query('SELECT id FROM cyclotron_jobs WHERE id = $1 FOR UPDATE', [lockedId])

                    const result = await manager.rescheduleParkedJobs({
                        teamId: 1,
                        functionId,
                        actionIds: ['delay_1'],
                    })

                    expect(result.swept).toBe(1)
                    expect(result.done).toBe(false)
                    expect(new Date((await queryJob(freeId)).scheduled).getTime()).toBeLessThanOrEqual(
                        result.sweepUntil.getTime() + 1000
                    )
                    expect(new Date((await queryJob(lockedId)).scheduled).getTime()).toBeGreaterThan(
                        Date.now() + 6 * 24 * 3600 * 1000
                    )
                } finally {
                    await client.query('ROLLBACK')
                    client.release()
                }
            })

            it('returns done immediately when nothing is parked beyond the floor', async () => {
                const result = await manager.rescheduleParkedJobs({
                    teamId: 1,
                    functionId: uuidv7(),
                    actionIds: ['delay_1'],
                })
                expect(result).toMatchObject({ swept: 0, remaining: 0, done: true })
            })

            it('rejects an empty action id list', async () => {
                await expect(
                    manager.rescheduleParkedJobs({ teamId: 1, functionId: uuidv7(), actionIds: [] })
                ).rejects.toThrow(/at least one action id/)
            })
        })

        it.each([
            ['one queue', [QUEUE, 0], [QUEUE, 0]],
            ['two queues and priority classes', [QUEUE, 1], ['other-queue', 2]],
        ])('backpressure throws when queue depth exceeds limit across %s', async (_label, first, second) => {
            const smallManager = createManager({ depthLimit: 2, depthCheckIntervalMs: 0 })
            await smallManager.connect()
            try {
                await smallManager.createJob({ teamId: 1, queueName: QUEUE, scheduled: new Date(Date.now() + 60_000) })
                for (const [queueName, priority] of [first, second] as [string, number][]) {
                    await smallManager.createJob({ teamId: 1, queueName, priority })
                }
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

            it.each([
                ['ack', 'completed'],
                ['cancel', 'canceled'],
            ] as const)(
                'createJob with overwriteExisting=true resets an existing terminal row to available (%s)',
                async (release, terminalStatus) => {
                    const id = uuidv7()
                    // First insert + drive to terminal state via the worker.
                    await manager.createJob({ id, teamId: 1, queueName: QUEUE, state: Buffer.from('v1') })
                    const worker = createWorker()
                    const jobs = await dequeueOneBatch(worker)
                    await jobs[0][release]()
                    expect((await queryJob(id)).status).toBe(terminalStatus)

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
                }
            )

            it.each([
                [
                    'createJob',
                    (id: string) =>
                        manager.createJob({
                            id,
                            teamId: 1,
                            queueName: 'email',
                            state: Buffer.from('rerun'),
                            overwriteExisting: true,
                        }),
                ],
                [
                    'bulkCreateJobs',
                    (id: string) =>
                        manager.bulkCreateJobs([
                            { id, teamId: 1, queueName: 'email', state: Buffer.from('rerun'), overwriteExisting: true },
                        ]),
                ],
            ])(
                '%s with overwriteExisting refuses to bring back a job canceled before any claim',
                async (_method, rerun) => {
                    const [id] = await manager.bulkCreateJobs([
                        {
                            teamId: 1,
                            queueName: 'email',
                            scheduled: new Date(Date.now() + 3600_000),
                            state: Buffer.from('v1'),
                        },
                    ])
                    await manager.cancelUnclaimed(1, id)

                    await expect(rerun(id)).rejects.toThrow(/canceled before it ran/)

                    expect(await queryJob(id)).toMatchObject({ status: 'canceled', state: Buffer.from('v1') })
                }
            )

            it('createJob with overwriteExisting=true reruns a row whose transition_count is at the smallint ceiling', async () => {
                const id = uuidv7()
                await manager.createJob({ id, teamId: 1, queueName: QUEUE })
                const worker = createWorker()
                const jobs = await dequeueOneBatch(worker)
                await jobs[0].ack()
                await assertPool.query('UPDATE cyclotron_jobs SET transition_count = $1 WHERE id = $2', [
                    CYCLOTRON_COUNTER_MAX,
                    id,
                ])

                await manager.createJob({ id, teamId: 1, queueName: QUEUE, overwriteExisting: true })

                const row = await queryJob(id)
                expect(row.status).toBe('available')
                expect(row.transition_count).toBe(CYCLOTRON_COUNTER_MAX)
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

        describe('resumeParkedSteps', () => {
            const parkedState = (jobId: string, actionId = 'task_node'): Buffer =>
                Buffer.from(
                    JSON.stringify({
                        state: {
                            currentAction: { id: actionId, awaitingResume: { key: `${jobId}:${actionId}:3` } },
                        },
                    })
                )
            const resumeFor = (jobId: string) => ({
                origin_key: `${jobId}:task_node:3`,
                status: 'completed' as const,
                result: { final_message: 'done' },
                jobId,
                actionId: 'task_node',
            })

            it('wakes a parked step of the team and stamps the result on it', async () => {
                const jobId = uuidv7()
                await manager.createJob({
                    id: jobId,
                    teamId: 1,
                    queueName: QUEUE,
                    functionId: uuidv7(),
                    scheduled: new Date(Date.now() + 3600 * 1000),
                    state: parkedState(jobId),
                })

                const outcomes = await manager.resumeParkedSteps(1, [resumeFor(jobId)])

                expect(outcomes.get(jobId)).toBe('delivered')
                expect(await jobIsDue(jobId)).toBe(true)
                const row = await queryJob(jobId)
                expect(parseJSON(row.state!.toString()).state.currentAction.resumeResult).toEqual({
                    key: `${jobId}:task_node:3`,
                    status: 'completed',
                    result: { final_message: 'done' },
                })
            })

            it("reports another team's job as missing rather than waking it", async () => {
                const jobId = uuidv7()
                await manager.createJob({
                    id: jobId,
                    teamId: 2,
                    queueName: QUEUE,
                    functionId: uuidv7(),
                    scheduled: new Date(Date.now() + 3600 * 1000),
                    state: parkedState(jobId),
                })

                const outcomes = await manager.resumeParkedSteps(1, [resumeFor(jobId)])

                expect(outcomes.get(jobId)).toBe('job_missing')
                expect(await jobIsDue(jobId)).toBe(false)
            })
        })

        describe('resumeParkedBatchResolver', () => {
            const parkResolver = async (teamId: number, functionId: string, batchJobId: string): Promise<string> =>
                await manager.createJob({
                    teamId,
                    queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
                    functionId,
                    parentRunId: batchJobId,
                    scheduled: new Date(Date.now() + 3600 * 1000),
                    state: serializeResolverState({
                        batchJobId,
                        teamId,
                        hogFlowId: functionId,
                        filters: { properties: [] },
                        variables: {},
                        realtimeCohort: { id: 7, teamId, waitUntil: new Date(Date.now() + 3600 * 1000).toISOString() },
                        maxAudienceSize: 100,
                        cursor: null,
                        totalEnqueued: 0,
                        pagesProcessed: 0,
                        attempts: 0,
                        startedAt: new Date().toISOString(),
                    }),
                })

            it('wakes the parked resolver of the batch and clears its wait, once', async () => {
                const functionId = uuidv7()
                const batchJobId = uuidv7()
                const jobId = await parkResolver(1, functionId, batchJobId)

                const first = await manager.resumeParkedBatchResolver({ teamId: 1, functionId, batchJobId })
                const second = await manager.resumeParkedBatchResolver({ teamId: 1, functionId, batchJobId })

                expect([first, second]).toEqual(['resumed', 'already_resumed'])
                expect(await jobIsDue(jobId)).toBe(true)
                const state = deserializeResolverState((await queryJob(jobId)).state)
                // Without the wait cleared, the resolver would park again and time out.
                expect(state.realtimeCohort).toEqual({ id: 7, teamId: 1 })
            })

            it.each([
                ['another team', 2, true],
                ['another batch', 1, false],
            ])('leaves the resolver of %s parked', async (_name, teamId, sameBatch) => {
                const functionId = uuidv7()
                const parkedBatchJobId = uuidv7()
                const jobId = await parkResolver(teamId, functionId, parkedBatchJobId)

                const outcome = await manager.resumeParkedBatchResolver({
                    teamId: 1,
                    functionId,
                    batchJobId: sameBatch ? parkedBatchJobId : uuidv7(),
                })

                expect(outcome).toBe('job_missing')
                expect(await jobIsDue(jobId)).toBe(false)
            })
        })

        describe('cancelJobs', () => {
            const FAR_FUTURE = () => new Date(Date.now() + 7 * 24 * 3600 * 1000)

            async function seedParked(functionId: string, over?: Partial<CyclotronV2JobInit>): Promise<string> {
                return await manager.createJob({
                    teamId: 1,
                    queueName: QUEUE,
                    functionId,
                    scheduled: FAR_FUTURE(),
                    ...over,
                })
            }

            it('jobIds mode: wakes and flags parked rows, flags running rows in place, leaves terminal rows untouched', async () => {
                const functionId = uuidv7()
                const parkedId = await seedParked(functionId)
                const runningId = await seedParked(functionId)
                await assertPool.query(`UPDATE cyclotron_jobs SET status = 'running' WHERE id = $1`, [runningId])
                const completedId = await seedParked(functionId)
                await assertPool.query(`UPDATE cyclotron_jobs SET status = 'completed' WHERE id = $1`, [completedId])

                const result = await manager.cancelJobs({
                    teamId: 1,
                    functionId,
                    jobIds: [parkedId, runningId, completedId, uuidv7()],
                })

                expect(result).toEqual({ marked: 2, remaining: 0, done: true })

                // Parked row: flagged AND woken, so the worker terminates it promptly
                // instead of after the remaining (potentially days-long) delay.
                const parked = await queryJob(parkedId)
                expect(parked.cancel_requested_at).not.toBeNull()
                expect(await jobIsDue(parkedId)).toBe(true)

                // Running row: flagged only. Its wake is pulled forward by the
                // worker's release, never by an external write racing the lock.
                const running = await queryJob(runningId)
                expect(running.cancel_requested_at).not.toBeNull()
                expect(await jobIsDue(runningId)).toBe(false)

                // Terminal row: untouched, so a later rerun doesn't inherit a flag.
                const completed = await queryJob(completedId)
                expect(completed.cancel_requested_at).toBeNull()
            })

            it('all mode: flags every in-flight row of the function across queues, and nothing beyond it', async () => {
                const functionId = uuidv7()
                const parkedId = await seedParked(functionId)
                const emailQueueId = await seedParked(functionId, { queueName: 'email' })
                const excludedQueueId = await seedParked(functionId, { queueName: 'orchestration' })
                const otherFunctionId = await seedParked(uuidv7())
                const otherTeamId = await seedParked(functionId, { teamId: 2 })

                const result = await manager.cancelJobs({
                    teamId: 1,
                    functionId,
                    all: true,
                    excludeQueueNames: ['orchestration'],
                })

                expect(result).toEqual({ marked: 2, remaining: 0, done: true })
                // A run's job can sit on another queue mid-step (e.g. email) - still flagged.
                expect((await queryJob(parkedId)).cancel_requested_at).not.toBeNull()
                expect((await queryJob(emailQueueId)).cancel_requested_at).not.toBeNull()
                // Excluded queues are neither flagged nor counted as remaining.
                expect((await queryJob(excludedQueueId)).cancel_requested_at).toBeNull()
                expect((await queryJob(otherFunctionId)).cancel_requested_at).toBeNull()
                expect((await queryJob(otherTeamId)).cancel_requested_at).toBeNull()
            })

            it("parentRunId mode: flags the run's resolver job and children, and nothing beyond the run", async () => {
                const functionId = uuidv7()
                const parentRunId = uuidv7()
                // The resolver orchestration job and its children share parent_run_id but
                // sit on different queues - one selector must flag all of them.
                const resolverId = await seedParked(functionId, { queueName: 'orchestration', parentRunId })
                const parkedChildId = await seedParked(functionId, { parentRunId })
                const runningChildId = await seedParked(functionId, { parentRunId })
                await assertPool.query(`UPDATE cyclotron_jobs SET status = 'running' WHERE id = $1`, [runningChildId])
                const otherRunId = await seedParked(functionId, { parentRunId: uuidv7() })
                const otherTeamId = await seedParked(functionId, { parentRunId, teamId: 2 })

                const result = await manager.cancelJobs({ teamId: 1, functionId, parentRunId })

                expect(result).toEqual({ marked: 3, remaining: 0, done: true })
                // Parked rows (resolver included) are flagged AND woken; the running child is
                // flagged in place, its wake pulled forward by the worker's release.
                const resolver = await queryJob(resolverId)
                expect(resolver.cancel_requested_at).not.toBeNull()
                expect(await jobIsDue(resolverId)).toBe(true)
                expect((await queryJob(parkedChildId)).cancel_requested_at).not.toBeNull()
                expect((await queryJob(runningChildId)).cancel_requested_at).not.toBeNull()
                expect((await queryJob(otherRunId)).cancel_requested_at).toBeNull()
                expect((await queryJob(otherTeamId)).cancel_requested_at).toBeNull()
            })

            it('rejects an empty parentRunId instead of widening to the whole workflow', async () => {
                await expect(manager.cancelJobs({ teamId: 1, functionId: uuidv7(), parentRunId: '' })).rejects.toThrow(
                    /non-empty/
                )
            })

            it('bulkCreateAndCheckIn refuses the page when a cancel flag landed while the worker held the job', async () => {
                const functionId = uuidv7()
                const parentRunId = uuidv7()
                const id = await manager.createJob({ teamId: 1, queueName: QUEUE, functionId, parentRunId })
                const worker = createWorker()
                const [job] = await dequeueOneBatch(worker)
                expect(job.id).toBe(id)

                // The mid-page window: the flag lands after the worker dequeued (and checked)
                // the job but before it commits the page it is building.
                await manager.cancelJobs({ teamId: 1, functionId, parentRunId })

                const result = await job.bulkCreateAndCheckIn({
                    newJobs: [{ teamId: 1, queueName: QUEUE, functionId, parentRunId }],
                    selfDisposition: { kind: 'reschedule', scheduledAt: FAR_FUTURE() },
                })

                expect(result).toEqual({ newJobIds: [], cancelRequested: true })
                // Nothing committed: no child row, and the self row kept its state.
                expect(await totalJobCount()).toBe(1)
                const row = await queryJob(id)
                expect(row.status).toBe('running')
                // The job is still held - the caller disposes of it.
                await job.cancel()
                expect((await queryJob(id)).status).toBe('canceled')
            })

            it('reports remaining and done=false when the chunk budget runs out, and the next call finishes', async () => {
                const functionId = uuidv7()
                await Promise.all(Array.from({ length: 3 }, () => seedParked(functionId)))
                const smallChunkManager = createManager({ rescheduleChunkSize: 2, rescheduleMaxChunksPerCall: 1 })

                const first = await smallChunkManager.cancelJobs({ teamId: 1, functionId, all: true })
                expect(first).toEqual({ marked: 2, remaining: 1, done: false })

                const second = await smallChunkManager.cancelJobs({ teamId: 1, functionId, all: true })
                expect(second).toEqual({ marked: 1, remaining: 0, done: true })

                await smallChunkManager.disconnect()
            })

            it('a worker releasing a flagged job wakes it immediately instead of honoring the requested delay', async () => {
                const functionId = uuidv7()
                const id = await manager.createJob({ teamId: 1, queueName: QUEUE, functionId })
                const worker = createWorker()
                const [job] = await dequeueOneBatch(worker)
                expect(job.id).toBe(id)

                await manager.cancelJobs({ teamId: 1, functionId, jobIds: [id] })
                await job.reschedule({ scheduledAt: FAR_FUTURE() })

                const row = await queryJob(id)
                expect(row.status).toBe('available')
                expect(await jobIsDue(id)).toBe(true)
            })

            it('dequeued jobs expose cancelRequestedAt so consumers can terminate instead of executing', async () => {
                const functionId = uuidv7()
                const id = await manager.createJob({
                    teamId: 1,
                    queueName: QUEUE,
                    functionId,
                    scheduled: FAR_FUTURE(),
                })
                await manager.cancelJobs({ teamId: 1, functionId, jobIds: [id] })

                const worker = createWorker()
                const [job] = await dequeueOneBatch(worker)
                expect(job.id).toBe(id)
                expect(job.cancelRequestedAt).not.toBeNull()
            })

            it('overwriteExisting re-enqueue clears the flag so a rerun does not instantly self-cancel', async () => {
                const functionId = uuidv7()
                const id = await seedParked(functionId)
                await manager.cancelJobs({ teamId: 1, functionId, jobIds: [id] })
                await assertPool.query(
                    `UPDATE cyclotron_jobs SET status = 'canceled', transition_count = transition_count + 1 WHERE id = $1`,
                    [id]
                )

                await manager.createJob({ id, teamId: 1, queueName: QUEUE, functionId, overwriteExisting: true })

                const row = await queryJob(id)
                expect(row.status).toBe('available')
                expect(row.cancel_requested_at).toBeNull()
            })

            it.each([
                ['no selector', {}],
                ['two selectors', { jobIds: [uuidv7()], all: true }],
                ['two selectors (parentRunId and all)', { parentRunId: uuidv7(), all: true }],
            ])('rejects a call with %s instead of guessing scope', async (_name, selector) => {
                await expect(manager.cancelJobs({ teamId: 1, functionId: uuidv7(), ...selector })).rejects.toThrow(
                    /exactly one selector/
                )
            })

            it('empty jobIds is a no-op', async () => {
                const result = await manager.cancelJobs({ teamId: 1, functionId: uuidv7(), jobIds: [] })
                expect(result).toEqual({ marked: 0, remaining: 0, done: true })
            })
        })

        describe('cancelUnclaimed and rescheduleUnclaimed', () => {
            const IN_A_WEEK = (): Date => new Date(Date.now() + 7 * 24 * 3600 * 1000)
            const IN_TWO_DAYS = new Date(Date.now() + 2 * 24 * 3600 * 1000)
            const storedState = { state: { scheduledAt: 'original', html: 'a\u0000b' }, queueParameters: { x: 1 } }

            async function seedScheduledEmail(teamId = 1): Promise<string> {
                const [id] = await manager.bulkCreateJobs([
                    {
                        teamId,
                        queueName: 'email',
                        functionId: uuidv7(),
                        scheduled: IN_A_WEEK(),
                        state: Buffer.from(JSON.stringify(storedState)),
                    },
                ])
                return id
            }

            const claimSql = `UPDATE cyclotron_jobs
                SET status = 'running', lock_id = gen_random_uuid(), transition_count = transition_count + 1
                WHERE id = $1`

            const operations = [
                ['cancelUnclaimed', (teamId: number, id: string) => manager.cancelUnclaimed(teamId, id)],
                [
                    'rescheduleUnclaimed',
                    (teamId: number, id: string) => manager.rescheduleUnclaimed(teamId, id, IN_TWO_DAYS),
                ],
            ] as const

            it('cancels an unclaimed email job so no worker claims it, once', async () => {
                const id = await seedScheduledEmail()

                const first = await manager.cancelUnclaimed(1, id)
                const repeat = await manager.cancelUnclaimed(1, id)

                expect(first).toMatchObject({
                    outcome: 'canceled',
                    job: { id, teamId: 1, queueName: 'email', state: Buffer.from(JSON.stringify(storedState)) },
                })
                expect(repeat).toEqual({
                    outcome: 'already_canceled',
                    job: first.outcome === 'canceled' ? first.job : null,
                })
                expect(await queryJob(id)).toMatchObject({ status: 'canceled', transition_count: 0, lock_id: null })
            })

            it('moves an unclaimed email job and its stored scheduledAt, keeping its place in the fair order', async () => {
                const id = await seedScheduledEmail()
                const before = await queryJob(id)

                const result = await manager.rescheduleUnclaimed(1, id, IN_TWO_DAYS)

                const row = await queryJob(id)
                expect(result).toMatchObject({ outcome: 'rescheduled', job: { id, teamId: 1, state: row.state } })
                expect(new Date(row.scheduled)).toEqual(IN_TWO_DAYS)
                expect(parseJSON(row.state!.toString())).toEqual({
                    ...storedState,
                    state: {
                        ...storedState.state,
                        scheduledAt: IN_TWO_DAYS.toISOString(),
                        statusAt: (result as { rescheduledAt: Date }).rescheduledAt.toISOString(),
                    },
                })
                expect(row).toMatchObject({ status: 'available', transition_count: 0 })
                expect(row.dequeue_seq).toEqual(before.dequeue_seq)
            })

            it('times a reschedule after the stored time of the previous status row, even when that is ahead', async () => {
                const id = await seedScheduledEmail()
                const ahead = new Date(Date.now() + 60_000)
                await assertPool.query(`UPDATE cyclotron_jobs SET state = $2 WHERE id = $1`, [
                    id,
                    Buffer.from(JSON.stringify({ state: { statusAt: ahead.toISOString() } })),
                ])

                const result = await manager.rescheduleUnclaimed(1, id, IN_TWO_DAYS)

                expect(result).toMatchObject({ outcome: 'rescheduled', rescheduledAt: new Date(ahead.getTime() + 1) })
            })

            it('times a reschedule that waited on the row lock after the commit it waited for', async () => {
                const id = await seedScheduledEmail()
                const client = await assertPool.connect()
                try {
                    await client.query('BEGIN')
                    await client.query(`SELECT 1 FROM cyclotron_jobs WHERE id = $1 FOR UPDATE`, [id])

                    const pending = manager.rescheduleUnclaimed(1, id, IN_TWO_DAYS)
                    await waitForExpect(async () => {
                        const waiting = await assertPool.query(
                            `SELECT 1 FROM pg_stat_activity
                             WHERE datname = current_database() AND wait_event_type = 'Lock'`
                        )
                        expect(waiting.rows).toHaveLength(1)
                    })
                    const beforeCommit = Date.now()
                    await client.query('COMMIT')

                    const result = await pending
                    expect(result).toMatchObject({ outcome: 'rescheduled', rescheduledAt: expect.any(Date) })
                    const { rescheduledAt } = result as { rescheduledAt: Date }
                    expect(rescheduledAt.getTime()).toBeGreaterThanOrEqual(beforeCommit)
                } finally {
                    client.release()
                }
            })

            it.each(operations)(
                '%s waits for a claim in progress and then reports the job claimed',
                async (_op, run) => {
                    const id = await seedScheduledEmail()
                    const client = await assertPool.connect()
                    try {
                        await client.query('BEGIN')
                        await client.query(claimSql, [id])

                        const pending = run(1, id)
                        await waitForExpect(async () => {
                            const waiting = await assertPool.query(
                                `SELECT 1 FROM pg_stat_activity
                             WHERE datname = current_database() AND wait_event_type = 'Lock'`
                            )
                            expect(waiting.rows).toHaveLength(1)
                        })
                        await client.query('COMMIT')

                        expect(await pending).toEqual({ outcome: 'claimed' })
                    } finally {
                        client.release()
                    }
                    expect(await queryJob(id)).toMatchObject({ status: 'running', transition_count: 1 })
                }
            )

            it.each([
                ['cancelUnclaimed', 'a claimed job', { outcome: 'claimed' }, 'claim'],
                ['cancelUnclaimed', "another team's job", { outcome: 'not_found' }, 'other_team'],
                ['cancelUnclaimed', 'an unknown id', { outcome: 'not_found' }, 'unknown'],
                ['cancelUnclaimed', 'a job on another queue', { outcome: 'not_found' }, 'other_queue'],
                [
                    'cancelUnclaimed',
                    'a job canceled after its claim',
                    { outcome: 'already_canceled', job: null },
                    'claim_cancel',
                ],
                ['rescheduleUnclaimed', 'a claimed job', { outcome: 'claimed' }, 'claim'],
                ['rescheduleUnclaimed', "another team's job", { outcome: 'not_found' }, 'other_team'],
                ['rescheduleUnclaimed', 'an unknown id', { outcome: 'not_found' }, 'unknown'],
                ['rescheduleUnclaimed', 'a job on another queue', { outcome: 'not_found' }, 'other_queue'],
                ['rescheduleUnclaimed', 'a job canceled before its claim', { outcome: 'canceled' }, 'cancel_unclaimed'],
                ['rescheduleUnclaimed', 'a job flagged by a run cancel', { outcome: 'canceled' }, 'cancel_flag'],
            ] as const)('%s on %s answers %o and changes nothing', async (op, _desc, expected, setup) => {
                let id =
                    setup === 'other_queue'
                        ? await manager.createJob({ teamId: 1, queueName: QUEUE, scheduled: IN_A_WEEK() })
                        : await seedScheduledEmail(setup === 'other_team' ? 2 : 1)
                if (setup === 'claim' || setup === 'claim_cancel') {
                    await assertPool.query(claimSql, [id])
                }
                if (setup === 'claim_cancel') {
                    await assertPool.query(
                        `UPDATE cyclotron_jobs SET status = 'canceled', lock_id = NULL WHERE id = $1`,
                        [id]
                    )
                } else if (setup === 'cancel_unclaimed') {
                    await manager.cancelUnclaimed(1, id)
                } else if (setup === 'cancel_flag') {
                    const { function_id } = await queryJob(id)
                    await manager.cancelJobs({ teamId: 1, functionId: function_id!, jobIds: [id] })
                }
                const before = await queryJob(id)
                if (setup === 'unknown') {
                    id = uuidv7()
                }

                const result = await Object.fromEntries(operations)[op](1, id)

                expect(result).toEqual(expected)
                expect(await queryJob(before.id)).toEqual(before)
            })
        })

        describe('createJobsIdempotently', () => {
            const keyed = (
                id: string,
                fingerprint: string,
                job: Partial<CyclotronV2JobInit> = {}
            ): CyclotronV2IdempotentJobInit => ({
                job: { teamId: 1, queueName: QUEUE, ...job, id },
                fingerprint,
            })

            it('queues one job per id and tells a repeat from a reused key', async () => {
                const id = uuidv7()

                expect(await manager.createJobsIdempotently([keyed(id, 'a')])).toEqual(['created'])
                expect(await manager.createJobsIdempotently([keyed(id.toUpperCase(), 'a')])).toEqual(['replayed'])
                expect(await manager.createJobsIdempotently([keyed(id, 'b')])).toEqual(['mismatch'])
                expect(await totalJobCount()).toBe(1)
            })

            it('leaves no key behind when the job insert fails, so the retry queues the job', async () => {
                const id = uuidv7()

                const priorityTooLargeForSmallint = 40_000
                await expect(
                    manager.createJobsIdempotently([keyed(id, 'a', { priority: priorityTooLargeForSmallint })])
                ).rejects.toThrow()

                expect(await manager.createJobsIdempotently([keyed(id, 'a')])).toEqual(['created'])
                expect(await totalJobCount()).toBe(1)
            })

            it.each([
                ['reclaims it once its job is gone', true, ['created']],
                ['keeps it while its job still exists', false, ['mismatch']],
            ])('for an expired key the janitor has not swept, %s', async (_name, jobGone, expected) => {
                const id = uuidv7()
                await manager.createJobsIdempotently([keyed(id, 'a')])
                if (jobGone) {
                    await assertPool.query('DELETE FROM cyclotron_jobs WHERE id = $1', [id])
                }
                await assertPool.query(
                    `UPDATE cyclotron_idempotency_keys SET expires_at = NOW() - interval '1 second' WHERE id = $1`,
                    [id]
                )

                expect(await manager.createJobsIdempotently([keyed(id, 'b')])).toEqual(expected)
                expect(await totalJobCount()).toBe(1)
            })

            it('answers a repeat while the queue is full, and still refuses a new key', async () => {
                const id = uuidv7()
                expect(await manager.createJobsIdempotently([keyed(id, 'a')])).toEqual(['created'])
                const fullManager = createManager({ depthLimit: 1, depthCheckIntervalMs: 0 })
                await fullManager.connect()
                try {
                    expect(await fullManager.createJobsIdempotently([keyed(id, 'a')])).toEqual(['replayed'])
                    expect(await fullManager.createJobsIdempotently([keyed(id, 'b')])).toEqual(['mismatch'])
                    await expect(fullManager.createJobsIdempotently([keyed(uuidv7(), 'a')])).rejects.toThrow(
                        /queue is full/i
                    )
                } finally {
                    await fullManager.disconnect()
                }
                expect(await totalJobCount()).toBe(1)
            })

            it('still refuses a key that a full queue would reclaim after it was read as taken', async () => {
                const id = uuidv7()
                await manager.createJobsIdempotently([keyed(id, 'a')])
                await assertPool.query('DELETE FROM cyclotron_jobs WHERE id = $1', [id])
                await assertPool.query(
                    `UPDATE cyclotron_idempotency_keys SET expires_at = NOW() - interval '1 second' WHERE id = $1`,
                    [id]
                )
                await manager.createJob({ teamId: 1, queueName: QUEUE })
                // One connection, so a depth check that asks the pool for a second one while the claim holds the
                // first would wait forever.
                const fullManager = createManager({
                    pool: { dbUrl: DB_URL, maxConnections: 1 },
                    depthLimit: 1,
                    depthCheckIntervalMs: 0,
                })
                await fullManager.connect()
                // The key expiring with its job gone between the read and the claim can't be timed from outside,
                // because the claim's NOW() is fixed when its transaction begins. So the read reports it as taken.
                jest.spyOn(fullManager as any, 'liveIdempotencyKeyIds').mockResolvedValue(new Set([id]))
                try {
                    await expect(fullManager.createJobsIdempotently([keyed(id, 'b')])).rejects.toThrow(/queue is full/i)
                } finally {
                    await fullManager.disconnect()
                }
                const { rows } = await assertPool.query<{ fingerprint: string; expired: boolean }>(
                    'SELECT fingerprint, expires_at <= NOW() AS expired FROM cyclotron_idempotency_keys WHERE id = $1',
                    [id]
                )
                expect(rows).toEqual([{ fingerprint: 'a', expired: true }])
                expect(await totalJobCount()).toBe(1)
            }, 5000)

            it("still refuses that key while a plain insert waits on the claim's only connection", async () => {
                const id = uuidv7()
                await manager.createJobsIdempotently([keyed(id, 'a')])
                await assertPool.query('DELETE FROM cyclotron_jobs WHERE id = $1', [id])
                await assertPool.query(
                    `UPDATE cyclotron_idempotency_keys SET expires_at = NOW() - interval '1 second' WHERE id = $1`,
                    [id]
                )
                await manager.createJob({ teamId: 1, queueName: QUEUE })
                // Caching on, so a plain insert's pool-backed depth check, waiting for the connection the claim
                // holds, would be shared with the claim's own check.
                const fullManager = createManager({
                    pool: { dbUrl: DB_URL, maxConnections: 1 },
                    depthLimit: 1,
                    depthCheckIntervalMs: 60_000,
                })
                await fullManager.connect()
                jest.spyOn(fullManager as any, 'liveIdempotencyKeyIds').mockResolvedValue(new Set([id]))
                const pool = (fullManager as any).pool as Pool
                const connect = pool.connect.bind(pool)
                let plainInsert: Promise<unknown> | undefined
                jest.spyOn(pool, 'connect').mockImplementationOnce(async () => {
                    const client = await connect()
                    // Starts once the claim holds the only connection, so its depth check has to wait for it.
                    plainInsert = fullManager.createJob({ teamId: 1, queueName: QUEUE }).catch((err) => err)
                    await new Promise((resolve) => setImmediate(resolve))
                    return client
                })
                try {
                    await expect(fullManager.createJobsIdempotently([keyed(id, 'b')])).rejects.toThrow(/queue is full/i)
                    await expect(plainInsert).resolves.toBeInstanceOf(Error)
                } finally {
                    await fullManager.disconnect()
                }
                expect(await totalJobCount()).toBe(1)
            }, 5000)

            it('takes an email dequeue slot only for a job it queues', async () => {
                const teamId = 4242
                const emailCounter = async (): Promise<string | undefined> =>
                    (
                        await assertPool.query<{ counter: string }>(
                            'SELECT counter FROM cyclotron_email_team_seq WHERE team_id = $1',
                            [teamId]
                        )
                    ).rows[0]?.counter
                const email = (id: string, fingerprint: string): CyclotronV2IdempotentJobInit =>
                    keyed(id, fingerprint, { teamId, queueName: 'email' })
                const id = uuidv7()

                expect(await manager.createJobsIdempotently([email(id, 'a')])).toEqual(['created'])
                const afterCreate = await emailCounter()
                expect(afterCreate).toBeDefined()

                expect(await manager.createJobsIdempotently([email(id, 'a')])).toEqual(['replayed'])
                expect(await manager.createJobsIdempotently([email(id, 'b')])).toEqual(['mismatch'])
                expect(await emailCounter()).toBe(afterCreate)

                expect(await manager.createJobsIdempotently([email(uuidv7(), 'a')])).toEqual(['created'])
                expect(BigInt((await emailCounter())!)).toBe(BigInt(afterCreate!) + 1n)
            })

            it('does not deadlock when concurrent calls carry the same ids in opposite orders', async () => {
                const [first, second] = [uuidv7(), uuidv7()].sort()
                await manager.createJobsIdempotently([keyed(first, 'a'), keyed(second, 'a')])
                // Both calls queue for `first` in order. Unsorted, the reversed call would hold `second` and deadlock.
                const blocker = await assertPool.connect()
                await blocker.query('BEGIN')
                await blocker.query('SELECT id FROM cyclotron_idempotency_keys WHERE id = $1 FOR UPDATE', [first])
                const inOrder = manager.createJobsIdempotently([keyed(first, 'a'), keyed(second, 'a')])
                await waitForExpect(async () => expect(await backendsWaitingOnLocks()).toBe(1), 2000, 10)
                const reversed = manager.createJobsIdempotently([keyed(second, 'a'), keyed(first, 'a')])
                await waitForExpect(async () => expect(await backendsWaitingOnLocks()).toBe(2), 2000, 10)
                await blocker.query('ROLLBACK')
                blocker.release()

                expect(await Promise.all([inOrder, reversed])).toEqual([
                    ['replayed', 'replayed'],
                    ['replayed', 'replayed'],
                ])
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

        // The loop swallows errors and retries, so a queue whose batches all throw looks
        // exactly like an idle queue. The counter is the only externally visible signal.
        it.each([
            ['the plain worker', 'loop-errors-plain', (): CyclotronV2Worker => createWorker('loop-errors-plain')],
            [
                'the rate-limited worker',
                'loop-errors-limited',
                (): CyclotronV2Worker =>
                    new CyclotronV2RateLimitedWorker(
                        {
                            pool: { dbUrl: DB_URL },
                            queueName: 'loop-errors-limited',
                            batchMaxSize: 100,
                            pollDelayMs: 10,
                        },
                        () => Promise.resolve(undefined)
                    ),
            ],
        ])('counts a consumer loop error in %s', async (_name, queue, makeWorker) => {
            await manager.createJob({ teamId: 1, queueName: queue })
            const before = await loopErrorCountForQueue(queue)
            const worker = makeWorker()

            let threw = false
            await new Promise<void>((resolve) => {
                void worker.connect(async (batch) => {
                    if (batch.length > 0 && !threw) {
                        threw = true
                        resolve()
                        return Promise.reject(new Error('processing failed'))
                    }
                })
            })
            // The throw resolves the promise before the loop's catch runs; give the
            // catch a moment to record it before stopping the loop.
            const deadline = Date.now() + 2_000
            while ((await loopErrorCountForQueue(queue)) - before < 1 && Date.now() < deadline) {
                await sleep(25)
            }
            await worker.stopConsuming()

            expect((await loopErrorCountForQueue(queue)) - before).toBe(1)
        })

        const rateLimitedWorker = (
            queue: string,
            overrides?: Record<string, unknown>,
            batchLimit: CyclotronV2BatchLimit | undefined = undefined
        ): CyclotronV2Worker =>
            new CyclotronV2RateLimitedWorker(
                { pool: { dbUrl: DB_URL }, queueName: queue, batchMaxSize: 100, pollDelayMs: 10, ...overrides },
                () => Promise.resolve(batchLimit)
            )

        it.each([
            ['the plain worker', 'backoff-plain', createWorker, { pollDelayMaxMs: 80 }, false, [10, 20, 40, 80, 80]],
            [
                'the rate-limited worker',
                'backoff-limited',
                rateLimitedWorker,
                { pollDelayMaxMs: 80 },
                false,
                [10, 20, 40, 80, 80],
            ],
            [
                'the rate-limited worker while another worker holds the visible job',
                'backoff-limited-locked',
                rateLimitedWorker,
                { pollDelayMaxMs: 80 },
                true,
                [10, 20, 40, 80, 80],
            ],
            ['the plain worker without a cap', 'backoff-plain-default', createWorker, {}, false, [10, 10, 10]],
            [
                'the plain worker with a cap that is not a number',
                'backoff-plain-nan',
                createWorker,
                { pollDelayMaxMs: NaN },
                false,
                [10, 10, 10],
            ],
            [
                'the rate-limited worker without a cap',
                'backoff-limited-default',
                rateLimitedWorker,
                {},
                false,
                [10, 10, 10],
            ],
        ])(
            'spaces the empty polls of %s',
            async (_name, queue, makeWorker, overrides, lockVisibleJob, expectedIntervals) => {
                const releaseLock = lockVisibleJob ? await holdDueJobLocked(manager, queue) : null
                try {
                    const intervals = await emptyPollIntervals(
                        makeWorker(queue, overrides),
                        queue,
                        expectedIntervals.length
                    )

                    expect(intervals).toEqual(expectedIntervals)
                } finally {
                    await releaseLock?.()
                }
            }
        )

        it.each([
            ['the plain worker', 'backoff-errors-plain', createWorker],
            ['the rate-limited worker', 'backoff-errors-limited', rateLimitedWorker],
        ])('spaces the failed polls of %s', async (_name, queue, makeWorker) => {
            const missingTable = `${DB_URL}?options=${encodeURIComponent('-c search_path=no_such_schema')}`

            const intervals = await pollIntervals(
                makeWorker(queue, { pollDelayMaxMs: 80, pool: { dbUrl: missingTable } }),
                () => loopErrorCountForQueue(queue),
                5
            )

            expect(intervals).toEqual([10, 20, 40, 80, 80])
        })

        it.each([
            ['the plain worker', 'backoff-reset-plain', createWorker],
            ['the rate-limited worker', 'backoff-reset-limited', rateLimitedWorker],
        ])('polls at the base delay again after %s gets a job', async (_name, queue, makeWorker) => {
            const jobPollsBefore = await pollCountForQueue(queue, 'jobs')

            const intervals = await emptyPollIntervals(makeWorker(queue, { pollDelayMaxMs: 80 }), queue, 5, (poll) =>
                poll === 4
                    ? manager.createJob({ teamId: 1, queueName: queue, scheduled: new Date(Date.now() - 60_000) })
                    : Promise.resolve()
            )

            expect(intervals).toEqual([10, 20, 40, 80, 10])
            expect((await pollCountForQueue(queue, 'jobs')) - jobPollsBefore).toBe(1)
        })

        it.each([
            [
                'an idle sleep',
                'stop-idle',
                'empty',
                false,
                (queue: string) => createWorker(queue, { pollDelayMs: 10_000 }),
            ],
            [
                'a throttled sleep',
                'stop-throttled',
                'throttled',
                true,
                (queue: string) => rateLimitedWorker(queue, {}, { limit: 0, sleepMs: 10_000 }),
            ],
        ])('stops without waiting out %s', async (_name, queue, outcome, seedJob, makeWorker) => {
            if (seedJob) {
                await manager.createJob({ teamId: 1, queueName: queue })
            }
            const pollsBefore = await pollCountForQueue(queue, outcome)
            const worker = makeWorker(queue)
            useFakeClockWithRealIo()
            try {
                await worker.connect(async () => {})
                await waitForWorkerToSettle(
                    `a ${outcome} poll`,
                    async () => (await pollCountForQueue(queue, outcome)) > pollsBefore
                )

                let stopped = false
                const stopping = worker.stopConsuming().then(() => {
                    stopped = true
                })
                await waitForWorkerToSettle('stopConsuming to return', () => Promise.resolve(stopped))
                await stopping
            } finally {
                await worker.disconnect()
                jest.useRealTimers()
            }
        })

        it('rejects a delay cap that would fail the heartbeat health check', () => {
            expect(() => createWorker(QUEUE, { pollDelayMaxMs: 20_000, heartbeatTimeoutMs: 30_000 })).toThrow(
                'pollDelayMaxMs'
            )
        })

        it('keeps accepting a long fixed poll delay when backoff is off', async () => {
            const worker = createWorker(QUEUE, { pollDelayMs: 20_000, heartbeatTimeoutMs: 30_000 })
            await worker.disconnect()
        })

        // Both dequeue paths bump transition_count for the whole batch in one UPDATE, so an
        // unclamped increment on a saturated row aborts the statement and stops every job on
        // the queue, not just the saturated one. 'email' selects the fair path, a separate
        // statement and the one the outage actually aborted.
        it.each([
            ['the plain dequeue', QUEUE],
            ['the fair dequeue', 'email'],
        ])('dequeues via %s alongside a job at the smallint ceiling', async (_label, queue) => {
            // Backdate both so neither can miss the poll's `scheduled <= NOW()` window.
            const scheduled = new Date(Date.now() - 60_000)
            const saturated = await manager.createJob({ teamId: 1, queueName: queue, scheduled })
            const healthy = await manager.createJob({ teamId: 1, queueName: queue, scheduled })
            await assertPool.query('UPDATE cyclotron_jobs SET transition_count = $1 WHERE id = $2', [
                CYCLOTRON_COUNTER_MAX,
                saturated,
            ])

            const jobs = await dequeueOneBatch(createWorker(queue))

            expect(jobs.map((j) => j.id).sort()).toEqual([saturated, healthy].sort())
            const { rows } = await assertPool.query('SELECT transition_count FROM cyclotron_jobs WHERE id = $1', [
                saturated,
            ])
            expect(rows[0].transition_count).toBe(CYCLOTRON_COUNTER_MAX)
        })

        // The loop that saturates a counter is claim, refuse, reschedule, so the release bumps
        // it a second time per cycle and has to be clamped too.
        it('reschedules a job at the smallint ceiling', async () => {
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            await assertPool.query('UPDATE cyclotron_jobs SET transition_count = $1 WHERE id = $2', [
                CYCLOTRON_COUNTER_MAX,
                id,
            ])

            const [job] = await dequeueOneBatch(createWorker())
            await job.reschedule()

            const row = await queryJob(id)
            expect(row.status).toBe('available')
            expect(row.transition_count).toBe(CYCLOTRON_COUNTER_MAX)
        })

        it.each(
            [
                ['every due class fits in the batch', 100, [2, 0, 1], [0, 1, 2]],
                ['the batch is smaller than the due rows', 3, [32000, 2, -5, 1, 0, 2], [-5, 0, 1]],
            ].flatMap(([label, ...rest]) => [
                [`${label}, bounded polls`, ...rest, true],
                [`${label}, legacy polls`, ...rest, false],
            ]) as [string, number, number[], number[], boolean][]
        )(
            'respects priority ordering (lower number = higher priority) when %s',
            async (_label, batchMaxSize, priorities, expected, boundedPolls) => {
                await manager.createJob({
                    teamId: 1,
                    queueName: QUEUE,
                    priority: -10,
                    scheduled: new Date(Date.now() + 60_000),
                })
                for (const priority of priorities) {
                    await manager.createJob({ teamId: 1, queueName: QUEUE, priority })
                }

                const jobs = await dequeueOneBatch(createWorker(QUEUE, { batchMaxSize, boundedPolls }))

                expect(jobs.map((j) => j.priority)).toEqual(expected)
            }
        )

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

        // Guards against the reschedule options schema silently stripping `priority`
        // (zod .parse drops unknown keys), which would break the email queue's
        // class assignment on the hogflow → email reschedule path.
        it.each([
            [{ priority: 10 }, 10],
            [{}, 1],
        ])('reschedule with options %o leaves the row at priority %i', async (options, expected) => {
            const { id, job } = await seedAndDequeue({ priority: 1 })

            await job.reschedule(options)

            const res = await assertPool.query('SELECT priority FROM cyclotron_jobs WHERE id = $1', [id])
            expect(res.rows[0].priority).toBe(expected)
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

            it.each(['ack', 'fail', 'reschedule'] as const)(
                'checks self in via %s and zeros janitor_touch_count (consecutive-stall counting)',
                async (kind) => {
                    const { id: parentId, job } = await seedAndDequeue()
                    // Simulate prior stalls the janitor had counted.
                    await assertPool.query('UPDATE cyclotron_jobs SET janitor_touch_count = 2 WHERE id = $1', [
                        parentId,
                    ])

                    await job.bulkCreateAndCheckIn({
                        newJobs: [],
                        selfDisposition:
                            kind === 'reschedule' ? { kind: 'reschedule', scheduledAt: new Date() } : { kind },
                    })

                    // A deliberate self-checkin is a healthy release — the count resets.
                    expect((await queryJob(parentId)).janitor_touch_count).toBe(0)
                }
            )

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
                        boundedPolls: true,
                        ...overrides,
                    },
                    getBatchLimit
                )

            const tokenBucket = (capacity: number) => {
                let tokens = capacity
                return {
                    take: (requested: number): Promise<CyclotronV2BatchLimit> => {
                        const granted = Math.min(requested, tokens)
                        tokens -= granted
                        return Promise.resolve({ limit: granted })
                    },
                    tokens: () => tokens,
                }
            }

            async function firstBatchWithTokensLeft(
                worker: CyclotronV2RateLimitedWorker,
                bucket: ReturnType<typeof tokenBucket>
            ): Promise<{ jobs: number; tokensLeft: number }> {
                let timer: ReturnType<typeof setTimeout> | undefined
                try {
                    return await new Promise((resolve, reject) => {
                        timer = setTimeout(() => reject(new Error('the worker dequeued no batch')), 2000)
                        worker
                            .connect((batch) => {
                                if (batch.length > 0) {
                                    resolve({ jobs: batch.length, tokensLeft: bucket.tokens() })
                                }
                                return Promise.resolve()
                            })
                            .catch(reject)
                    })
                } finally {
                    clearTimeout(timer)
                    await worker.disconnect()
                }
            }

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
                let resolveFirstPoll!: () => void
                const firstPoll = new Promise<void>((resolve) => {
                    resolveFirstPoll = resolve
                })

                class ObservedRateLimitedWorker extends CyclotronV2RateLimitedWorker {
                    protected override countWork(limit: number): Promise<number> {
                        resolveFirstPoll()
                        return super.countWork(limit)
                    }
                }
                const worker = new ObservedRateLimitedWorker(
                    {
                        pool: { dbUrl: DB_URL },
                        queueName: QUEUE,
                        batchMaxSize: 100,
                        pollDelayMs: 10,
                        includeEmptyBatches: true,
                    },
                    () => {
                        hookCalls += 1
                        return Promise.resolve({ limit: 5 })
                    }
                )

                await worker.connect(async () => {})
                await firstPoll
                await worker.stopConsuming()

                // The worker completed an idle poll, so the limiter hook is never invoked.
                expect(hookCalls).toBe(0)
            })

            it.each([
                ['one priority class', [0, 0, 0]],
                ['several priority classes', [2, 0, 1]],
            ])('takes only as many tokens as rows are due across %s', async (_label, priorities) => {
                await manager.bulkCreateJobs([
                    ...priorities.map((priority) => ({ teamId: 1, queueName: QUEUE, priority })),
                    { teamId: 1, queueName: QUEUE, priority: -1, scheduled: new Date(Date.now() + 60_000) },
                ])
                const bucket = tokenBucket(100)

                const firstBatch = await firstBatchWithTokensLeft(createRateLimitedWorker(bucket.take), bucket)

                expect(firstBatch).toEqual({ jobs: 3, tokensLeft: 97 })
            })

            it.each([
                ['one priority class', () => 0],
                ['several priority classes', (i: number) => i % 3],
            ])('takes no more tokens than batchMaxSize across %s', async (_label, priorityOf) => {
                await manager.bulkCreateJobs(
                    Array.from({ length: 10 }, (_, i) => ({ teamId: 1, queueName: QUEUE, priority: priorityOf(i) }))
                )
                const bucket = tokenBucket(100)

                const firstBatch = await firstBatchWithTokensLeft(
                    createRateLimitedWorker(bucket.take, { batchMaxSize: 4 }),
                    bucket
                )

                expect(firstBatch).toEqual({ jobs: 4, tokensLeft: 96 })
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

        it.each(['ack', 'fail', 'cancel'] as const)(
            '%s() resets janitor_touch_count to 0 on a deliberate release',
            async (method) => {
                const { id, job } = await seedAndDequeue()
                // Simulate prior stalls the janitor had counted.
                await assertPool.query('UPDATE cyclotron_jobs SET janitor_touch_count = 2 WHERE id = $1', [id])

                await job[method]()

                expect((await queryJob(id)).janitor_touch_count).toBe(0)
            }
        )

        it('reschedule() resets janitor_touch_count to 0 so the poison budget counts consecutive stalls', async () => {
            const { id, job } = await seedAndDequeue()
            await assertPool.query('UPDATE cyclotron_jobs SET janitor_touch_count = 2 WHERE id = $1', [id])

            await job.reschedule()

            expect((await queryJob(id)).janitor_touch_count).toBe(0)
        })

        it.each([
            {
                written: 'during the hold, for the step it parks on',
                key: 'wait-a',
                at: 'clock_timestamp()',
                opts: true,
                due: true,
                kept: true,
            },
            {
                written: 'before the hold',
                key: 'wait-a',
                at: "last_transition - interval '1 second'",
                opts: true,
                due: false,
                kept: false,
            },
            {
                written: 'during the hold, for another step',
                key: 'wait-b',
                at: 'clock_timestamp()',
                opts: true,
                due: false,
                kept: false,
            },
            {
                written: 'during the hold, by a park that keeps its backoff',
                key: 'wait-a',
                at: 'clock_timestamp()',
                opts: false,
                due: false,
                kept: true,
            },
        ])(
            'reschedule() onto a wait with a wake recorded $written wakes it: $due',
            async ({ key, at, opts, due, kept }) => {
                const { id, job } = await seedAndDequeue({ actionId: 'wait-a' })
                await assertPool.query(
                    `UPDATE cyclotron_jobs SET pending_wake = jsonb_build_object($2::text, jsonb_build_object('kind', 'match', 'at', ${at})) WHERE id = $1`,
                    [id, key]
                )

                await job.reschedule({
                    actionId: 'wait-a',
                    scheduledAt: new Date(Date.now() + 3600_000),
                    wakeOnPendingWake: opts,
                })

                expect(await jobIsDue(id)).toBe(due)
                const row = await queryJob(id)
                expect(Object.keys(row.pending_wake ?? {})).toEqual(kept ? ['wait-a'] : [])
            }
        )

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

        it('heartbeat() renews a job while its release write is pending, stops past the limit, and refuses once it settles', async () => {
            const releaseWriteHeartbeatLimitMs = 5_000
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            const [job] = await dequeueOneBatch(createWorker(QUEUE, { releaseWriteHeartbeatLimitMs }))

            const blocker = await assertPool.connect()
            jest.useFakeTimers({
                doNotFake: ['nextTick', 'setImmediate', 'setTimeout', 'setInterval', 'queueMicrotask'],
            })
            try {
                await blocker.query('BEGIN')
                await blocker.query(
                    `INSERT INTO cyclotron_email_team_seq (team_id, counter) VALUES (1, 1)
                     ON CONFLICT (team_id) DO UPDATE SET counter = cyclotron_email_team_seq.counter`
                )
                const rescheduled = job.reschedule({ queueName: 'email' })

                await makeHeartbeatStale(id)
                await job.heartbeat()
                expect(await heartbeatIsFresh(id)).toBe(true)

                await makeHeartbeatStale(id)
                jest.setSystemTime(Date.now() + releaseWriteHeartbeatLimitMs + 1)
                await expect(job.heartbeat()).rejects.toThrow('already released')
                expect(await heartbeatIsFresh(id)).toBe(false)

                jest.useRealTimers()
                await blocker.query('COMMIT')
                await rescheduled
            } finally {
                jest.useRealTimers()
                await blocker.query('ROLLBACK')
                blocker.release()
            }

            await expect(job.heartbeat()).rejects.toThrow('already released')
            expect((await queryJob(id)).status).toBe('available')
        })

        it('heartbeat() skips without waiting while another client holds the job row, then renews once it is free', async () => {
            const { id, job } = await seedAndDequeue()
            await makeHeartbeatStale(id)

            const rowHolder = await assertPool.connect()
            try {
                await rowHolder.query('BEGIN')
                await rowHolder.query('SELECT id FROM cyclotron_jobs WHERE id = $1 FOR UPDATE', [id])

                await expect(settlesWithin(job.heartbeat(), 2_000)).resolves.toBe(true)
                expect(await heartbeatIsFresh(id)).toBe(false)

                await rowHolder.query('COMMIT')
            } finally {
                await rowHolder.query('ROLLBACK')
                rowHolder.release()
            }

            await job.heartbeat()
            expect(await heartbeatIsFresh(id)).toBe(true)
            expect((await queryJob(id)).status).toBe('running')
        }, 10_000)

        it('double-release throws on second ack method call', async () => {
            const { job } = await seedAndDequeue()

            await job.ack()
            await expect(job.fail()).rejects.toThrow(/already released/)
            await expect(job.reschedule()).rejects.toThrow(/already released/)
            await expect(job.cancel()).rejects.toThrow(/already released/)
            await expect(job.heartbeat()).rejects.toThrow(/already released/)
        })

        it.each([
            ['the plain dequeue', QUEUE],
            ['the fair dequeue', 'email'],
        ])('concurrent workers get disjoint batches via %s', async (_label, queue) => {
            for (let i = 0; i < 10; i++) {
                await manager.createJob({ teamId: 1 + (i % 3), queueName: queue })
            }

            const worker1 = createWorker(queue, { batchMaxSize: 5 })
            const worker2 = createWorker(queue, { batchMaxSize: 5 })

            const [batch1, batch2] = await Promise.all([dequeueOneBatch(worker1), dequeueOneBatch(worker2)])

            const allIds = [...batch1.map((j) => j.id), ...batch2.map((j) => j.id)]
            expect(allIds).toHaveLength(10)
            expect(new Set(allIds).size).toBe(10)
        })

        it('leaves the due rows a dequeue does not claim to other workers', async () => {
            const scheduled = new Date(Date.now() - 60_000)
            for (const priority of [0, 1, 2]) {
                await manager.createJob({ teamId: 1, queueName: QUEUE, priority, scheduled })
            }
            const heldWorker = 'cyclotron-held-claim'
            const claimLock = 4242
            await assertPool.query(`
                CREATE OR REPLACE FUNCTION cyclotron_test_hold_claim() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF current_setting('application_name') = '${heldWorker}' THEN
                        PERFORM pg_advisory_xact_lock(${claimLock});
                    END IF;
                    RETURN NEW;
                END $$`)
            await assertPool.query(
                'CREATE TRIGGER cyclotron_test_hold_claim BEFORE UPDATE ON cyclotron_jobs FOR EACH ROW EXECUTE FUNCTION cyclotron_test_hold_claim()'
            )
            const gate = await assertPool.connect()
            let heldBatch: Promise<CyclotronV2DequeuedJob[]> = Promise.resolve([])
            try {
                await gate.query('SELECT pg_advisory_lock($1)', [claimLock])
                heldBatch = dequeueOneBatch(
                    createWorker(QUEUE, {
                        batchMaxSize: 1,
                        pool: { dbUrl: `${DB_URL}?application_name=${heldWorker}` },
                    })
                )
                await waitForExpect(
                    async () => {
                        const { rows } = await assertPool.query(
                            `SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
                             WHERE a.application_name = $1 AND l.locktype = 'advisory' AND NOT l.granted`,
                            [heldWorker]
                        )
                        expect(rows).toHaveLength(1)
                    },
                    2000,
                    10
                )

                const other = await dequeueOneBatch(createWorker(QUEUE, { batchMaxSize: 1 }), 500)

                expect(other.map((job) => job.priority)).toEqual([1])
            } finally {
                await gate.query('SELECT pg_advisory_unlock_all()')
                gate.release()
                await heldBatch
                await assertPool.query('DROP TRIGGER cyclotron_test_hold_claim ON cyclotron_jobs')
                await assertPool.query('DROP FUNCTION cyclotron_test_hold_claim()')
            }
            expect((await heldBatch).map((job) => job.priority)).toEqual([0])
        })

        it('transition_count increments on dequeue', async () => {
            const { id, job } = await seedAndDequeue()

            expect(job.transitionCount).toBe(1)
            const row = await queryJob(id)
            expect(row.transition_count).toBe(1)
        })

        it.each([
            ['below the churn threshold', CYCLOTRON_TRANSITION_CHURN_THRESHOLD - 2, 0],
            ['at the churn threshold', CYCLOTRON_TRANSITION_CHURN_THRESHOLD - 1, 1],
        ])('counts a dequeue %s', async (_label, seeded, expected) => {
            const before = await churnCountForQueue(QUEUE)
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            await assertPool.query('UPDATE cyclotron_jobs SET transition_count = $1 WHERE id = $2', [seeded, id])

            await dequeueOneBatch(createWorker())

            expect((await churnCountForQueue(QUEUE)) - before).toBe(expected)
        })
    })

    describe('polling cost with a backlog scheduled for later', () => {
        const PROBE_SCHEMA = 'polling_cost_probe'
        const BACKLOG_QUEUE = 'future-backlog'
        const BACKLOG_ROWS = 20_000
        const BACKLOG_BUFFER_BUDGET = 30
        const BACKLOG_BUFFER_BUDGET_WITH_CLAIM_INDEX_WRITES = 80

        type PlanMode = 'custom' | 'generic'

        function sessionUrl(applicationName: string, mode: PlanMode): string {
            const options = `-c search_path=${PROBE_SCHEMA} -c plan_cache_mode=force_${mode}_plan`
            return `${DB_URL}?application_name=${applicationName}&options=${encodeURIComponent(options)}`
        }

        async function untilSessionStatsFlushed(applicationName: string): Promise<void> {
            await waitForExpect(async () => expect(await backendsNamed(applicationName)).toBe(0), 2000, 10)
        }

        async function buffersTouched(): Promise<number> {
            const { rows } = await assertPool.query<{ n: number }>(
                `SELECT (COALESCE(heap_blks_hit, 0) + COALESCE(heap_blks_read, 0)
                       + COALESCE(idx_blks_hit, 0) + COALESCE(idx_blks_read, 0))::int AS n
                 FROM pg_statio_all_tables WHERE relid = $1::regclass`,
                [`${PROBE_SCHEMA}.cyclotron_jobs`]
            )
            return rows[0].n
        }

        async function seed(queue: string, dueJobs: number, backlogJobs: number): Promise<void> {
            const applicationName = 'polling-cost-seed'
            const client = new Client({ connectionString: sessionUrl(applicationName, 'custom') })
            await client.connect()
            try {
                await client.query('TRUNCATE cyclotron_jobs')
                await client.query(
                    `INSERT INTO cyclotron_jobs (id, team_id, queue_name, status, priority, scheduled, created, last_transition, dequeue_seq)
                     SELECT gen_random_uuid(), 1, $1, 'available', (g % 3)::smallint,
                            CASE WHEN g <= $3 THEN NOW() - interval '1 minute'
                                 ELSE NOW() + interval '1 hour' + g * interval '1 minute' END,
                            NOW(), NOW(),
                            CASE WHEN g <= $3 THEN $2::int + g ELSE g - $3::int END AS future_rows_take_the_lowest_dequeue_seq
                     FROM generate_series(1, $2::int + $3::int) g`,
                    [queue, backlogJobs, dueJobs]
                )
                await client.query('VACUUM ANALYZE cyclotron_jobs')
            } finally {
                await client.end()
            }
            await untilSessionStatsFlushed(applicationName)
        }

        beforeAll(async () => {
            await assertPool.query(`DROP SCHEMA IF EXISTS ${PROBE_SCHEMA} CASCADE`)
            await assertPool.query(`CREATE SCHEMA ${PROBE_SCHEMA}`)
            await assertPool.query(
                `CREATE TABLE ${PROBE_SCHEMA}.cyclotron_jobs (LIKE public.cyclotron_jobs INCLUDING ALL)
                 WITH (autovacuum_enabled = false)`
            )
        })

        afterAll(async () => {
            await assertPool.query(`DROP SCHEMA ${PROBE_SCHEMA} CASCADE`)
        })

        async function pollOnce(
            worker: CyclotronV2Worker,
            polled: Promise<void>,
            processBatch: () => Promise<void> = () => Promise.resolve()
        ): Promise<void> {
            let timer: ReturnType<typeof setTimeout> | undefined
            try {
                await worker.connect(processBatch)
                await Promise.race([
                    polled,
                    new Promise<never>((_, reject) => {
                        timer = setTimeout(() => reject(new Error('the worker did not finish a poll')), 1000)
                    }),
                ])
            } finally {
                clearTimeout(timer)
                await worker.disconnect()
            }
        }

        function pollSignal(): { polled: Promise<void>; markPolled: () => void } {
            let markPolled: () => void = () => {}
            const polled = new Promise<void>((resolve) => (markPolled = resolve))
            return { polled, markPolled }
        }

        const PARAMETERIZED_SQL_PLANS: PlanMode[] = ['custom', 'generic']
        const PLAIN_SQL_PLANS: PlanMode[] = ['custom']
        const operations: [string, string, number, number, PlanMode[], (dbUrl: string) => Promise<void>][] = [
            [
                'the worker dequeue',
                BACKLOG_QUEUE,
                0,
                BACKLOG_BUFFER_BUDGET,
                PARAMETERIZED_SQL_PLANS,
                async (dbUrl) => {
                    const { polled, markPolled } = pollSignal()
                    await pollOnce(createWorker(BACKLOG_QUEUE, { pool: { dbUrl } }), polled, () =>
                        Promise.resolve(markPolled())
                    )
                },
            ],
            [
                'the email fair dequeue',
                'email',
                1,
                BACKLOG_BUFFER_BUDGET_WITH_CLAIM_INDEX_WRITES,
                PARAMETERIZED_SQL_PLANS,
                async (dbUrl) => {
                    const { polled, markPolled } = pollSignal()
                    await pollOnce(createWorker('email', { pool: { dbUrl } }), polled, () =>
                        Promise.resolve(markPolled())
                    )
                },
            ],
            [
                'the rate-limited worker count',
                BACKLOG_QUEUE,
                1,
                BACKLOG_BUFFER_BUDGET,
                PARAMETERIZED_SQL_PLANS,
                async (dbUrl) => {
                    const { polled, markPolled } = pollSignal()
                    const worker = new CyclotronV2RateLimitedWorker(
                        { pool: { dbUrl }, queueName: BACKLOG_QUEUE, pollDelayMs: 10, boundedPolls: true },
                        () => {
                            markPolled()
                            return Promise.resolve({ limit: 0 })
                        }
                    )
                    await pollOnce(worker, polled)
                },
            ],
            [
                'the manager depth check',
                BACKLOG_QUEUE,
                0,
                BACKLOG_BUFFER_BUDGET,
                PLAIN_SQL_PLANS,
                async (dbUrl) => {
                    const depthChecked = createManager({ pool: { dbUrl }, depthLimit: 0 })
                    try {
                        await expect(depthChecked.createJob({ teamId: 1, queueName: BACKLOG_QUEUE })).rejects.toThrow(
                            'queue is full'
                        )
                    } finally {
                        await depthChecked.disconnect()
                    }
                },
            ],
            [
                'the janitor depth gauges',
                BACKLOG_QUEUE,
                0,
                BACKLOG_BUFFER_BUDGET,
                PLAIN_SQL_PLANS,
                async (dbUrl) => {
                    const janitor = createJanitor({ pool: { dbUrl } })
                    try {
                        await janitor.measureQueueDepths()
                    } finally {
                        await janitor.stop()
                    }
                },
            ],
        ]
        const cases = operations.flatMap(([label, queue, dueJobs, budget, modes, operation]) =>
            modes.map((mode) => [label, mode, queue, dueJobs, budget, operation] as const)
        )

        async function buffersReadBy(operation: (dbUrl: string) => Promise<void>, mode: PlanMode): Promise<number> {
            const applicationName = 'polling-cost-operation'
            const before = await buffersTouched()
            await operation(sessionUrl(applicationName, mode))
            await untilSessionStatsFlushed(applicationName)
            return (await buffersTouched()) - before
        }

        it.each(cases)(
            '%s does not read through a backlog scheduled for later under a %s plan',
            async (_label, mode, queue, dueJobs, budget, operation) => {
                await seed(queue, dueJobs, 0)
                const withoutBacklog = await buffersReadBy(operation, mode)
                await seed(queue, dueJobs, BACKLOG_ROWS)
                const withBacklog = await buffersReadBy(operation, mode)

                expect(withBacklog - withoutBacklog).toBeLessThan(budget)
            }
        )

        async function seedEmailAfterAnalyze(emailBacklogJobs: number): Promise<void> {
            const applicationName = 'polling-cost-seed'
            const client = new Client({ connectionString: sessionUrl(applicationName, 'custom') })
            await client.connect()
            try {
                await client.query('TRUNCATE cyclotron_jobs')
                await client.query(
                    `INSERT INTO cyclotron_jobs (id, team_id, queue_name, status, priority, scheduled, created, last_transition)
                     SELECT gen_random_uuid(), 1, $1, 'available', (g % 3)::smallint,
                            NOW() + interval '1 hour' + g * interval '1 minute', NOW(), NOW()
                     FROM generate_series(1, $2::int) g`,
                    [BACKLOG_QUEUE, BACKLOG_ROWS * 2]
                )
                await client.query('ANALYZE cyclotron_jobs')
                await client.query(
                    `INSERT INTO cyclotron_jobs (id, team_id, queue_name, status, priority, scheduled, created, last_transition, dequeue_seq)
                     SELECT gen_random_uuid(), 1, 'email', 'available', (g % 3)::smallint,
                            CASE WHEN g = 1 THEN NOW() - interval '1 minute'
                                 ELSE NOW() + interval '1 hour' + g * interval '1 minute' END,
                            NOW(), NOW(),
                            CASE WHEN g = 1 THEN $1::int + 1 ELSE g - 1 END
                     FROM generate_series(1, $1::int + 1) g`,
                    [emailBacklogJobs]
                )
                await client.query('VACUUM cyclotron_jobs')
            } finally {
                await client.end()
            }
            await untilSessionStatsFlushed(applicationName)
        }

        it.each(PARAMETERIZED_SQL_PLANS)(
            'the email fair dequeue does not read through an email backlog the statistics have not seen under a %s plan',
            async (mode) => {
                const claimOnce = async (dbUrl: string): Promise<void> => {
                    const { polled, markPolled } = pollSignal()
                    await pollOnce(createWorker('email', { pool: { dbUrl } }), polled, () =>
                        Promise.resolve(markPolled())
                    )
                }
                await seedEmailAfterAnalyze(0)
                const withoutBacklog = await buffersReadBy(claimOnce, mode)
                await seedEmailAfterAnalyze(BACKLOG_ROWS)
                const withBacklog = await buffersReadBy(claimOnce, mode)

                expect(withBacklog - withoutBacklog).toBeLessThan(BACKLOG_BUFFER_BUDGET_WITH_CLAIM_INDEX_WRITES)
            }
        )
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

            it.each<{
                write: string
                prepare: () => Promise<() => Promise<unknown>>
                expected: Record<string, number>
            }>([
                {
                    write: 'a manager batch of an email and a hogflow job',
                    prepare: () =>
                        Promise.resolve(() =>
                            manager.bulkCreateJobs([
                                { teamId: 7, queueName: EMAIL_QUEUE },
                                { teamId: 7, queueName: 'hogflow' },
                            ])
                        ),
                    expected: { 'manager:depth_check': 1, 'manager:sequence_reserve': 1, 'manager:insert': 1 },
                },
                {
                    write: 'a manager batch of hogflow jobs',
                    prepare: () =>
                        Promise.resolve(() =>
                            manager.bulkCreateJobs([
                                { teamId: 7, queueName: 'hogflow' },
                                { teamId: 7, queueName: 'hogflow' },
                            ])
                        ),
                    expected: { 'manager:depth_check': 1, 'manager:insert': 1 },
                },
                {
                    write: 'a single manager job',
                    prepare: () => Promise.resolve(() => manager.createJob({ teamId: 7, queueName: 'hogflow' })),
                    expected: { 'manager:depth_check': 1, 'manager:insert': 1 },
                },
                {
                    write: 'a worker moving its job into the email queue',
                    prepare: async () => {
                        const { job } = await seedAndDequeue({ teamId: 7 })
                        return () => job.reschedule({ queueName: EMAIL_QUEUE })
                    },
                    expected: { 'worker:sequence_reserve': 1 },
                },
                {
                    write: 'a worker inserting children with its check-in',
                    prepare: async () => {
                        const { job } = await seedAndDequeue({ teamId: 7 })
                        return () =>
                            job.bulkCreateAndCheckIn({
                                newJobs: [{ teamId: 7, queueName: 'hogflow' }],
                                selfDisposition: { kind: 'ack' },
                            })
                    },
                    expected: { 'worker:insert': 1 },
                },
            ])('times each enqueue phase of $write', async ({ prepare, expected }) => {
                const step = await prepare()

                expect(await enqueuePhaseCountsDuring(step)).toEqual(expected)
            })

            it('times a held team sequence row into the sequence reserve', async () => {
                const holdMs = 100
                await manager.bulkCreateJobs([{ teamId: 7, queueName: EMAIL_QUEUE }])
                const holder = await assertPool.connect()
                let committed = false
                try {
                    await holder.query('BEGIN')
                    await holder.query('SELECT counter FROM cyclotron_email_team_seq WHERE team_id = 7 FOR UPDATE')
                    const holderPid = (await holder.query<{ pid: number }>('SELECT pg_backend_pid() AS pid')).rows[0]
                        .pid
                    const before = await managerSequenceReserveTotals()
                    const enqueued = manager.bulkCreateJobs([{ teamId: 7, queueName: EMAIL_QUEUE }])
                    await waitForExpect(async () => {
                        const blocked = await assertPool.query(
                            'SELECT pid FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid))',
                            [holderPid]
                        )
                        expect(blocked.rowCount).toBe(1)
                    })
                    const whileBlocked = await managerSequenceReserveTotals()
                    await sleep(holdMs)
                    await holder.query('COMMIT')
                    committed = true
                    await enqueued
                    const after = await managerSequenceReserveTotals()

                    expect(whileBlocked.count - before.count).toBe(0)
                    expect(after.count - before.count).toBe(1)
                    expect(after.seconds - before.seconds).toBeGreaterThanOrEqual((holdMs - 5) / 1000)
                } finally {
                    if (!committed) {
                        await holder.query('ROLLBACK')
                    }
                    holder.release()
                }
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

            it.each([
                [
                    'bulkCreateJobs',
                    async (teamId: number): Promise<void> => {
                        await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])
                    },
                ],
                [
                    'a reroute into the email queue',
                    async (teamId: number): Promise<void> => {
                        await manager.createJob({ teamId, queueName: 'hog' })
                        const [hogJob] = await dequeueOneBatch(createWorker('hog'))
                        await hogJob.reschedule({ queueName: EMAIL_QUEUE })
                    },
                ],
            ])(
                "starts a new team's counter at the existing max (Hatchet p_max_assigned) via %s",
                async (_path, assignOne) => {
                    // Without this, a brand-new tenant's burst would slot in at
                    // counter=1 and cut ahead of every established team's
                    // in-flight emails. Hatchet's pattern: first-ever insert for
                    // a team starts at `MAX(counter) + 1` across the table, so
                    // they line up *next to* existing teams instead of jumping
                    // the queue. Subsequent emails for that team keep
                    // incrementing normally.
                    await assignOne(1)
                    await assignOne(1)
                    // Team 2's first ever email → counter = max(2) + 1 = 3, not 1.
                    await assignOne(2)

                    expect(await readTeamCounter(1)).toBe(2n)
                    expect(await readTeamCounter(2)).toBe(3n)
                }
            )

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

        describe.each([
            ['bounded', true],
            ['legacy', false],
        ])('Worker: fairDequeue ordering, %s claim', (_label, boundedFairDequeue) => {
            // The email queue is intrinsically fair-dequeued — the worker derives
            // it from the queue name, so an EMAIL_QUEUE worker is already fair.
            const createFairWorker = (overrides?: Record<string, unknown>): CyclotronV2Worker =>
                createWorker(EMAIL_QUEUE, { boundedFairDequeue, ...overrides })

            it.each([
                {
                    label: 'a lower-sequence row of another team is parked',
                    seed: async (): Promise<string> => {
                        await manager.bulkCreateJobs([
                            { teamId: 200, queueName: EMAIL_QUEUE, scheduled: new Date(Date.now() + 3_600_000) },
                        ])
                        const [due] = await manager.bulkCreateJobs([{ teamId: 100, queueName: EMAIL_QUEUE }])
                        return due
                    },
                },
                {
                    label: 'more rows are due than the candidate cap',
                    seed: async (): Promise<string> => {
                        const [first] = await manager.bulkCreateJobs([
                            { teamId: 200, queueName: EMAIL_QUEUE, scheduled: new Date(Date.now() - 1_000) },
                        ])
                        await manager.bulkCreateJobs(
                            Array.from({ length: FAIR_DEQUEUE_CANDIDATE_CAP + 1 }, () => ({
                                teamId: 100,
                                queueName: EMAIL_QUEUE,
                                scheduled: new Date(Date.now() - 3_600_000),
                            }))
                        )
                        return first
                    },
                },
            ])('claims the lowest-sequence due row when $label', async ({ seed }) => {
                const expected = await seed()

                const jobs = await dequeueOneBatch(createFairWorker({ batchMaxSize: 1 }))

                expect(jobs.map((j) => j.id)).toEqual([expected])
            })

            it('dequeues the fast class before an earlier-enqueued bulk backlog', async () => {
                // A bulk broadcast (priority 1) is already queued when two fast-class
                // sends (priority 0) arrive, one from the same team. Without priority
                // ordering, the same-team fast job waits behind the whole backlog.
                const teamA = 100
                const teamB = 200
                await manager.bulkCreateJobs([
                    ...Array.from({ length: 5 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE, priority: 1 })),
                    { teamId: teamA, queueName: EMAIL_QUEUE, priority: 0 },
                    { teamId: teamB, queueName: EMAIL_QUEUE, priority: 0 },
                ])

                const worker = createFairWorker({ batchMaxSize: 2 })
                const jobs = await dequeueOneBatch(worker)

                expect(jobs.map((j) => j.priority)).toEqual([0, 0])
                expect(new Set(jobs.map((j) => j.teamId))).toEqual(new Set([teamA, teamB]))
            })

            it('keeps the per-team interleave within a priority class', async () => {
                const teamA = 100
                const teamB = 200
                await manager.bulkCreateJobs([
                    ...Array.from({ length: 2 }, () => ({ teamId: teamA, queueName: EMAIL_QUEUE, priority: 1 })),
                    ...Array.from({ length: 2 }, () => ({ teamId: teamB, queueName: EMAIL_QUEUE, priority: 1 })),
                    { teamId: teamA, queueName: EMAIL_QUEUE, priority: 0 },
                ])

                const drained: Array<[number, number]> = []
                for (let i = 0; i < 5; i++) {
                    const worker = createFairWorker({ batchMaxSize: 1 })
                    const batch = await dequeueOneBatch(worker)
                    expect(batch).toHaveLength(1)
                    drained.push([batch[0].priority, batch[0].teamId])
                    await batch[0].ack()
                }

                expect(drained).toEqual([
                    [0, teamA],
                    [1, teamA],
                    [1, teamB],
                    [1, teamA],
                    [1, teamB],
                ])
            })

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

            it('lands concurrent multi-team batches listing teams in opposite orders and keeps the interleave', async () => {
                const teamA = 100
                const teamB = 200
                const teamC = 300
                await manager.bulkCreateJobs(
                    [teamA, teamB, teamC].map((teamId) => ({ teamId, queueName: EMAIL_QUEUE }))
                )

                const applicationName = 'opposite-order-bulk-inserts'
                const racingManager = createManager({
                    pool: { dbUrl: `${DB_URL}?application_name=${applicationName}` },
                })
                await racingManager.connect()
                const blocker = await assertPool.connect()
                try {
                    await blocker.query('BEGIN')
                    await blocker.query('SELECT 1 FROM cyclotron_email_team_seq WHERE team_id = $1 FOR UPDATE', [teamC])

                    const settled = Promise.allSettled([
                        racingManager.bulkCreateJobs(
                            [teamB, teamC, teamA].map((teamId) => ({ teamId, queueName: EMAIL_QUEUE }))
                        ),
                        racingManager.bulkCreateJobs(
                            [teamA, teamC, teamB].map((teamId) => ({ teamId, queueName: EMAIL_QUEUE }))
                        ),
                    ])
                    await waitForExpect(
                        async () => {
                            const { rows } = await assertPool.query<{ n: number }>(
                                `SELECT COUNT(*)::int AS n FROM pg_stat_activity
                                 WHERE application_name = $1 AND cardinality(pg_blocking_pids(pid)) > 0`,
                                [applicationName]
                            )
                            expect(rows[0].n).toBe(2)
                        },
                        3000,
                        10
                    )
                    await blocker.query('COMMIT')

                    expect(await settled).toEqual([
                        expect.objectContaining({ status: 'fulfilled' }),
                        expect.objectContaining({ status: 'fulfilled' }),
                    ])
                } finally {
                    await blocker.query('ROLLBACK')
                    blocker.release()
                    await racingManager.disconnect()
                }

                const drained: number[] = []
                for (let i = 0; i < 9; i++) {
                    const batch = await dequeueOneBatch(createFairWorker({ batchMaxSize: 1 }))
                    expect(batch).toHaveLength(1)
                    drained.push(batch[0].teamId)
                    await batch[0].ack()
                }

                expect(drained).toEqual([teamA, teamB, teamC, teamA, teamB, teamC, teamA, teamB, teamC])
            }, 15_000)

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

            it.each([
                {
                    name: 'each established team',
                    queuedEmailTeams: [41, 42],
                    reroutedTeams: [41, 41, 41, 42, 42, 42],
                    emailTeamsQueuedAfter: [],
                    expectedDrain: [41, 42, 41, 42, 41, 42, 41, 42],
                },
                {
                    name: 'a team without a counter yet',
                    queuedEmailTeams: [41],
                    reroutedTeams: [42, 42, 42],
                    emailTeamsQueuedAfter: [41, 41, 41],
                    expectedDrain: [41, 41, 42, 41, 42, 41, 42],
                },
            ])(
                'gives concurrent reroutes into the email queue their own turn in fair order: $name',
                async ({ queuedEmailTeams, reroutedTeams, emailTeamsQueuedAfter, expectedDrain }) => {
                    await manager.bulkCreateJobs(queuedEmailTeams.map((teamId) => ({ teamId, queueName: EMAIL_QUEUE })))
                    await manager.bulkCreateJobs(reroutedTeams.map((teamId) => ({ teamId, queueName: 'hogflow' })))
                    const hogflowJobs = await dequeueOneBatch(createWorker('hogflow'))
                    expect(hogflowJobs).toHaveLength(reroutedTeams.length)

                    await Promise.all(hogflowJobs.map((job) => job.reschedule({ queueName: EMAIL_QUEUE })))
                    await manager.bulkCreateJobs(
                        emailTeamsQueuedAfter.map((teamId) => ({ teamId, queueName: EMAIL_QUEUE }))
                    )

                    const drained: number[] = []
                    for (let i = 0; i < expectedDrain.length; i++) {
                        const [emailJob] = await dequeueOneBatch(createFairWorker({ batchMaxSize: 1 }))
                        drained.push(emailJob.teamId)
                        await emailJob.ack()
                    }
                    expect(drained).toEqual(expectedDrain)
                }
            )

            it("reroutes a team's job into the email queue while another team in the batch has its counter row locked", async () => {
                const [lockedTeam, freeTeam] = [41, 42]
                await manager.bulkCreateJobs([
                    { teamId: lockedTeam, queueName: EMAIL_QUEUE },
                    { teamId: freeTeam, queueName: EMAIL_QUEUE },
                ])
                const earlierEmails = await dequeueOneBatch(createFairWorker())
                await Promise.all(earlierEmails.map((job) => job.ack()))
                await manager.bulkCreateJobs([
                    { teamId: lockedTeam, queueName: 'hogflow' },
                    { teamId: freeTeam, queueName: 'hogflow' },
                ])
                const hogflowJobs = await dequeueOneBatch(
                    createWorker('hogflow', { pool: { dbUrl: `${DB_URL}?options=-c%20lock_timeout%3D500` } })
                )
                const lockedTeamJob = hogflowJobs.find((job) => job.teamId === lockedTeam)!
                const freeTeamJob = hogflowJobs.find((job) => job.teamId === freeTeam)!

                const holder = await assertPool.connect()
                await holder.query('BEGIN')
                await holder.query('SELECT counter FROM cyclotron_email_team_seq WHERE team_id = $1 FOR UPDATE', [
                    lockedTeam,
                ])
                try {
                    const [lockedTeamReroute, freeTeamReroute] = await Promise.allSettled([
                        lockedTeamJob.reschedule({ queueName: EMAIL_QUEUE }),
                        freeTeamJob.reschedule({ queueName: EMAIL_QUEUE }),
                    ])

                    expect(freeTeamReroute.status).toBe('fulfilled')
                    expect(lockedTeamReroute.status).toBe('rejected')
                    const emailJobs = await dequeueOneBatch(createFairWorker())
                    expect(emailJobs.map((job) => job.id)).toEqual([freeTeamJob.id])
                } finally {
                    await holder.query('ROLLBACK')
                    holder.release()
                }
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

            it.each([
                ['keeps its state when given none', undefined],
                ['stores the state it is given', Buffer.from('{"queueMetadata":{"attachmentDeferrals":1}}')],
            ])('defer() sends a job to the back of its team turn, keeps its poison count, and %s', async (_, given) => {
                const teamId = 5
                const state = Buffer.from('{"queueMetadata":{"attachmentLoadTries":3}}')
                const [deferredId] = await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE, state }])
                const worker = createFairWorker({ batchMaxSize: 1 })
                try {
                    const [job] = await dequeueOneBatch(worker)
                    await assertPool.query('UPDATE cyclotron_jobs SET janitor_touch_count = 2 WHERE id = $1', [
                        deferredId,
                    ])
                    const [newerId] = await manager.bulkCreateJobs([{ teamId, queueName: EMAIL_QUEUE }])
                    const scheduledAt = new Date(Date.now() - 1_000)

                    await job.defer({ scheduledAt, state: given })

                    const row = await queryJob(deferredId)
                    expect(row).toMatchObject({
                        status: 'available',
                        lock_id: null,
                        janitor_touch_count: 2,
                        state: given ?? state,
                    })
                    expect(new Date(row.scheduled)).toEqual(scheduledAt)

                    const arrivals: string[] = []
                    for (let i = 0; i < 2; i++) {
                        const batch = await dequeueOneBatch(worker)
                        arrivals.push(...batch.map((j) => j.id))
                    }
                    expect(arrivals).toEqual([newerId, deferredId])
                } finally {
                    await worker.disconnect()
                }
            })
        })
    })

    // ── Janitor ──────────────────────────────────────────────────────

    describe('Janitor', () => {
        async function insertRawJob(overrides: Partial<RawJobRow> & { id: string }): Promise<void> {
            const defaults = {
                team_id: 1,
                function_id: null,
                // Default to a real invocation queue so a poisoned genuine invocation is recorded.
                // The janitor only records give-ups on invocation queues; anything else is a
                // wrapper/meta job that's dropped without a record (see WRAPPER drop tests below).
                queue_name: 'hogflow',
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

        // Backoff on the reset job's next scheduled time, keyed on
        // janitor_touch_count. The FIRST stall retries within the small jittered
        // spread (~5s), not the full base — the exponential term is shifted
        // (2^touch - 1 = 0 on the first strike) so a transient stall recovers fast.
        // Repeat stalls then pay a growing, capped backoff. Bounds are loose to
        // absorb jitter + db clock skew. maxTouchCount is high so these aren't given
        // up as poison before reset.
        it('resetStalledJobs retries the first stall fast (spread only, not the full base)', async () => {
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: new Date(Date.now() - 60_000),
                scheduled: new Date(Date.now() - 60_000),
                janitor_touch_count: 0,
            })

            const before = Date.now()
            const janitor = createJanitor({
                stallTimeoutMs: 1_000,
                stallBackoffBaseMs: 10_000,
                stallBackoffMaxMs: 600_000,
            })
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.stalled).toBe(1)
            const row = await queryJob(jobId)
            expect(row.status).toBe('available')
            const deferMs = new Date(row.scheduled).getTime() - before
            // Rescheduled to ~now (not left 60s in the past → backoff ran) but only
            // by the ~5s spread — well under the 10s base, so a first stall is fast.
            expect(deferMs).toBeGreaterThanOrEqual(-500)
            expect(deferMs).toBeLessThanOrEqual(6_000)
        })

        it.each([
            { touchCount: 1, baseMs: 10_000, maxMs: 600_000, minDeferMs: 4_000, maxDeferMs: 18_000 },
            { touchCount: 2, baseMs: 10_000, maxMs: 600_000, minDeferMs: 13_000, maxDeferMs: 38_000 },
            { touchCount: 2, baseMs: 10_000, maxMs: 5_000, minDeferMs: 2_000, maxDeferMs: 12_000 },
        ])(
            'resetStalledJobs backs off repeat stalls exponentially, capped (touch=$touchCount, cap=$maxMs)',
            async ({ touchCount, baseMs, maxMs, minDeferMs, maxDeferMs }) => {
                const jobId = uuidv7()
                await insertRawJob({
                    id: jobId,
                    status: 'running',
                    lock_id: uuidv7(),
                    last_heartbeat: new Date(Date.now() - 60_000),
                    janitor_touch_count: touchCount,
                })

                const before = Date.now()
                const janitor = createJanitor({
                    stallTimeoutMs: 1_000,
                    maxTouchCount: 100,
                    stallBackoffBaseMs: baseMs,
                    stallBackoffMaxMs: maxMs,
                })
                const result = await janitor.runOnce()
                await janitor.stop()

                expect(result.stalled).toBe(1)
                const row = await queryJob(jobId)
                expect(row.status).toBe('available')
                const deferMs = new Date(row.scheduled).getTime() - before
                expect(deferMs).toBeGreaterThan(minDeferMs)
                expect(deferMs).toBeLessThanOrEqual(maxDeferMs)
            }
        )

        it('resetStalledJobs leaves scheduled immediate when backoff is disabled (base 0)', async () => {
            const jobId = uuidv7()
            const pastScheduled = new Date(Date.now() - 5_000)
            await insertRawJob({
                id: jobId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: new Date(Date.now() - 60_000),
                scheduled: pastScheduled,
                janitor_touch_count: 0,
            })

            const before = Date.now()
            const janitor = createJanitor({ stallTimeoutMs: 1_000, stallBackoffBaseMs: 0 })
            await janitor.runOnce()
            await janitor.stop()

            const row = await queryJob(jobId)
            expect(row.status).toBe('available')
            // scheduled untouched → still in the past → immediately re-dequeuable.
            expect(new Date(row.scheduled).getTime()).toBeLessThanOrEqual(before)
        })

        it('records a poison pill as a failed result and deletes it once recorded', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                function_id: uuidv7(),
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 3,
            })

            const { service, recordTerminalFailureDurably } = createMockResults(true)
            const janitor = createJanitor({ stallTimeoutMs: 1_000, maxTouchCount: 2 }, service)
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.poisoned).toBe(1)
            expect(result.poisonedIds).toEqual([jobId])
            // Recorded as a failed, replayable invocation result first...
            expect(recordTerminalFailureDurably).toHaveBeenCalledTimes(1)
            expect(recordTerminalFailureDurably).toHaveBeenCalledWith(
                expect.objectContaining({ id: jobId }),
                expect.objectContaining({ errorKind: JANITOR_POISON_PILL_ERROR_KIND })
            )
            // ...then the cyclotron row is gone (no silent delete, no leftover).
            expect(await totalJobCount()).toBe(0)
        })

        // Both meta/wrapper queues share cyclotron_jobs with real invocations and
        // stamp function_id to a target function, so both must be dropped without a
        // record — else the autodrain replays a real flow with fabricated globals.
        // 'some_future_meta_queue' is an unknown, non-invocation queue: it guards the allow-list's
        // fail-safe. Under the old deny-list a queue nobody listed would be RECORDED as a replayable
        // hog_flow (the autodrain would then replay a phantom flow) — with the allow-list any queue
        // not in CYCLOTRON_INVOCATION_JOB_QUEUES is dropped without a record by default.
        it.each(['rerun', 'hogflow_batch_resolve', 'some_future_meta_queue'])(
            'drops a poisoned %s wrapper without recording it, still records real invocations',
            async (wrapperQueue) => {
                const staleHeartbeat = new Date(Date.now() - 60_000)
                const wrapperId = uuidv7()
                const invocationId = uuidv7()
                // A poisoned WRAPPER job and a genuine poisoned invocation, same sweep.
                await insertRawJob({
                    id: wrapperId,
                    function_id: uuidv7(),
                    queue_name: wrapperQueue,
                    status: 'running',
                    lock_id: uuidv7(),
                    last_heartbeat: staleHeartbeat,
                    janitor_touch_count: 3,
                })
                await insertRawJob({
                    id: invocationId,
                    function_id: uuidv7(),
                    status: 'running',
                    lock_id: uuidv7(),
                    last_heartbeat: staleHeartbeat,
                    janitor_touch_count: 3,
                })

                const { service, recordTerminalFailureDurably } = createMockResults(true)
                const janitor = createJanitor({ stallTimeoutMs: 1_000, maxTouchCount: 2 }, service)
                const result = await janitor.runOnce()
                await janitor.stop()

                // The wrapper is dropped with NO replay record — recording it would let
                // the autodrain rediscover it as a hog_flow and replay a real flow with
                // fabricated globals. Only the genuine invocation is recorded.
                expect(recordTerminalFailureDurably).toHaveBeenCalledTimes(1)
                expect(recordTerminalFailureDurably).toHaveBeenCalledWith(
                    expect.objectContaining({ id: invocationId }),
                    expect.anything()
                )
                expect(result.poisonedIds).toEqual([invocationId])
                // Both cyclotron rows are gone — the wrapper is given up on, just untraced.
                expect(await totalJobCount()).toBe(0)
            }
        )

        it('keeps a poison pill (does not delete) when the recovery record cannot be produced', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 3,
            })

            // produce fails → never delete, so the job is never silently dropped.
            const { service } = createMockResults(false)
            const janitor = createJanitor({ stallTimeoutMs: 1_000, maxTouchCount: 2 }, service)
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.poisoned).toBe(0)
            expect(await totalJobCount()).toBe(1)
            // It is still reset to available so a recovered worker retries it.
            expect((await queryJob(jobId)).status).toBe('available')
        })

        it('keeps poison pills (never deletes) when no results service is wired', async () => {
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

            expect(result.poisoned).toBe(0)
            expect(await totalJobCount()).toBe(1)
        })

        it('marks poison pills failed (legacy behavior, no record) when recovery is disabled (kill-switch)', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                status: 'running',
                lock_id: uuidv7(),
                last_heartbeat: staleHeartbeat,
                janitor_touch_count: 3,
            })

            // A results service is wired, but the kill-switch reverts to master's
            // pre-recovery path: mark the pill failed, never record a replay row.
            const { service, recordTerminalFailureDurably } = createMockResults(true)
            const janitor = createJanitor(
                { stallTimeoutMs: 1_000, maxTouchCount: 2, poisonRecoveryEnabled: false },
                service
            )
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.poisoned).toBe(1)
            expect(recordTerminalFailureDurably).not.toHaveBeenCalled()
            expect((await queryJob(jobId)).status).toBe('failed')
        })

        it('gives up on a job that keeps stalling between deferrals', async () => {
            const id = await manager.createJob({ teamId: 1, queueName: 'email', functionId: uuidv7() })
            const worker = createWorker('email')
            const resultsTopic = new InMemoryResultsTopic()
            const janitor = createJanitor(
                { stallTimeoutMs: 1_000, maxTouchCount: 2, stallBackoffBaseMs: 0 },
                new HogInvocationResultsService(resultsTopic, { HOG_INVOCATION_RESULTS_ENABLED: true })
            )
            const stallAndSweep = async (): Promise<CyclotronV2CleanupResult> => {
                const [job] = await dequeueOneBatch(worker)
                await job.defer({ scheduledAt: new Date(Date.now() - 1_000) })
                await dequeueOneBatch(worker)
                await assertPool.query(
                    `UPDATE cyclotron_jobs SET last_heartbeat = NOW() - INTERVAL '1 minute' WHERE id = $1`,
                    [id]
                )
                return janitor.runOnce()
            }

            try {
                expect((await stallAndSweep()).stalled).toBe(1)
                expect((await stallAndSweep()).stalled).toBe(1)
                expect(resultsTopic.rows).toEqual([])

                expect((await stallAndSweep()).poisonedIds).toEqual([id])
                expect(resultsTopic.rows).toEqual([
                    {
                        output: HOG_INVOCATION_RESULTS_OUTPUT,
                        row: expect.objectContaining({
                            invocation_id: id,
                            status: 'failed',
                            error_kind: JANITOR_POISON_PILL_ERROR_KIND,
                        }),
                    },
                ])
                expect(await totalJobCount()).toBe(0)
            } finally {
                await janitor.stop()
                await worker.disconnect()
            }
        })

        it('gives up on poison pills before stalled jobs are reset', async () => {
            const staleHeartbeat = new Date(Date.now() - 60_000)

            const poisonId = uuidv7()
            await insertRawJob({
                id: poisonId,
                function_id: uuidv7(),
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

            const { service } = createMockResults(true)
            const janitor = createJanitor({ stallTimeoutMs: 1_000, maxTouchCount: 2 }, service)
            const result = await janitor.runOnce()
            await janitor.stop()

            expect(result.poisoned).toBe(1)
            expect(result.stalled).toBe(1)

            // Poison pill recorded + deleted; the merely-stalled job survives, reset.
            await expect(queryJob(poisonId)).rejects.toThrow()
            const stalled = await queryJob(stalledId)
            expect(stalled.status).toBe('available')
        })

        it.each(['hogflow', 'email', 'emailsandbox'])(
            'builds and produces a valid failed hog_flow result for a poisoned %s-queue job',
            async (queueName) => {
                // Realistic parked-mid-flow state; the scheduled/created columns come
                // back from pg as ISO strings — the give-up row build must parse them
                // without throwing (the RangeError this guards against).
                const id = uuidv7()
                const functionId = uuidv7()
                const state = Buffer.from(
                    JSON.stringify({
                        state: {
                            event: { uuid: uuidv7(), distinct_id: 'd1' },
                            actionStepCount: 1,
                            variables: { foo: 'bar' },
                            currentAction: { id: 'wait_1', startedAtTimestamp: 1 },
                        },
                    })
                )
                await insertRawJob({
                    id,
                    function_id: functionId,
                    queue_name: queueName,
                    status: 'running',
                    lock_id: uuidv7(),
                    last_heartbeat: new Date(Date.now() - 60_000),
                    janitor_touch_count: 5,
                    state,
                })

                const resultsTopic = new InMemoryResultsTopic()
                const janitor = createJanitor(
                    { stallTimeoutMs: 1_000, maxTouchCount: 2 },
                    new HogInvocationResultsService(resultsTopic, { HOG_INVOCATION_RESULTS_ENABLED: true })
                )
                const result = await janitor.runOnce()
                await janitor.stop()

                expect(result.poisonedIds).toEqual([id])
                const clickhouseTimestamp = expect.stringMatching(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/)
                expect(resultsTopic.rows).toEqual([
                    {
                        output: HOG_INVOCATION_RESULTS_OUTPUT,
                        row: expect.objectContaining({
                            invocation_id: id,
                            status: 'failed',
                            function_kind: 'hog_flow',
                            function_id: functionId,
                            error_kind: JANITOR_POISON_PILL_ERROR_KIND,
                            scheduled_at: clickhouseTimestamp,
                            finished_at: clickhouseTimestamp,
                        }),
                    },
                ])
                expect(await totalJobCount()).toBe(0)
            }
        )

        it('measureQueueDepths reports 0 for a queue that drains', async () => {
            // GROUP BY returns no row for an empty queue. Without the zero write the gauge
            // keeps the last depth, and a depth alert then fires on an idle queue.
            const ageMetric = 'cdp_cyclotron_v2_queue_oldest_due_age_ms'
            const jobId = uuidv7()
            await insertRawJob({
                id: jobId,
                queue_name: 'queue-drains',
                status: 'available',
                scheduled: new Date(Date.now() - 30_000),
            })

            const janitor = createJanitor({ stallTimeoutMs: 60_000 })
            const before = await janitor.runOnce()
            expect(before.depths.get('queue-drains')).toBe(1)
            expect(await gaugeValueForQueue('queue-drains')).toBe(1)
            expect(await gaugeValueForQueue('queue-drains', ageMetric)).toBeGreaterThanOrEqual(30_000)
            expect(await gaugeValueForQueue('queue-drains', ageMetric)).toBeLessThan(60_000)

            await assertPool.query('DELETE FROM cyclotron_jobs WHERE id = $1', [jobId])
            await janitor.runOnce()
            await janitor.stop()

            expect(await gaugeValueForQueue('queue-drains')).toBe(0)
            expect(await gaugeValueForQueue('queue-drains', ageMetric)).toBe(0)
        })

        it('measureQueueDepths returns the count and oldest due age per queue across priority classes', async () => {
            await insertRawJob({
                id: uuidv7(),
                queue_name: 'queue-a',
                status: 'available',
                priority: 0,
                scheduled: new Date(Date.now() - 50_000),
            })
            await insertRawJob({
                id: uuidv7(),
                queue_name: 'queue-a',
                status: 'available',
                priority: 2,
                scheduled: new Date(Date.now() - 10_000),
            })
            await insertRawJob({ id: uuidv7(), queue_name: 'queue-b', status: 'available', priority: 1 })
            await insertRawJob({
                id: uuidv7(),
                queue_name: 'queue-b',
                status: 'available',
                priority: 0,
                scheduled: new Date(Date.now() + 60_000),
            })
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
            const oldestAgeMs = await gaugeValueForQueue('queue-a', 'cdp_cyclotron_v2_queue_oldest_due_age_ms')
            expect(oldestAgeMs).toBeGreaterThanOrEqual(50_000)
            expect(oldestAgeMs).toBeLessThan(60_000)
        })

        it('sweeps expired conversion watchers and idempotency keys and keeps live ones', async () => {
            // The sweep is the only thing that removes a watcher that never converts. If a refactor
            // drops it from runOnce the table grows without bound and nothing else fails, so assert
            // the delete happens on a real row.
            const insertWatcher = async (id: string, expiresAt: Date): Promise<void> => {
                await assertPool.query(
                    `INSERT INTO conversion_watchers
                     (id, team_id, function_id, run_id, distinct_id, goal, expires_at)
                     VALUES ($1, 1, $2, $1, $3, $4, $5)`,
                    [id, uuidv7(), `sweep-${id}`, JSON.stringify({ events: [] }), expiresAt]
                )
            }
            const expired = uuidv7()
            const live = uuidv7()
            await insertWatcher(expired, new Date(Date.now() - 60_000))
            await insertWatcher(live, new Date(Date.now() + 3_600_000))
            const insertKey = async (id: string, expiresAt: Date): Promise<void> => {
                await assertPool.query(
                    `INSERT INTO cyclotron_idempotency_keys (id, team_id, fingerprint, expires_at)
                     VALUES ($1, 1, 'fingerprint', $2)`,
                    [id, expiresAt]
                )
            }
            const expiredKey = uuidv7()
            const liveKey = uuidv7()
            const expiredKeyWithJob = uuidv7()
            const lockedKey = uuidv7()
            await insertKey(expiredKey, new Date(Date.now() - 60_000))
            await insertKey(liveKey, new Date(Date.now() + 3_600_000))
            await insertKey(expiredKeyWithJob, new Date(Date.now() - 60_000))
            await manager.createJob({ id: expiredKeyWithJob, teamId: 1, queueName: QUEUE })
            await insertKey(lockedKey, new Date(Date.now() - 60_000))
            const writer = await assertPool.connect()
            await writer.query('BEGIN')
            await writer.query('SELECT id FROM cyclotron_idempotency_keys WHERE id = $1 FOR UPDATE', [lockedKey])

            const janitor = createJanitor()
            await janitor.runOnce()
            await writer.query('ROLLBACK')
            writer.release()

            const remaining = await assertPool.query(`SELECT id FROM conversion_watchers WHERE id = ANY($1::uuid[])`, [
                [expired, live],
            ])
            expect(remaining.rows.map((r) => r.id)).toEqual([live])
            const remainingKeys = await assertPool.query(
                `SELECT id FROM cyclotron_idempotency_keys WHERE id = ANY($1::uuid[])`,
                [[expiredKey, liveKey, expiredKeyWithJob, lockedKey]]
            )
            expect(remainingKeys.rows.map((r) => r.id).sort()).toEqual([liveKey, expiredKeyWithJob, lockedKey].sort())

            await janitor.stop()
        })
    })

    describe('dropped Postgres connections', () => {
        const DROP_APP = 'cyclotron-v2-drop-test'
        const DROP_DB_URL = `${DB_URL}?application_name=${DROP_APP}`
        let stops: (() => Promise<unknown>)[] = []

        afterEach(async () => {
            await Promise.all(stops.map((stop) => stop()))
            stops = []
        })

        async function droppedClientCount(pool: string): Promise<number> {
            const metric = register.getSingleMetric('cdp_cyclotron_v2_pg_client_errors_total')
            const samples = metric ? (await metric.get()).values : []
            return samples.find((sample) => sample.labels.pool === pool)?.value ?? 0
        }

        async function terminateDropTestBackends(): Promise<void> {
            await assertPool.query(
                'SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = $1',
                [DROP_APP]
            )
        }

        async function dropIdleClients(pool: string): Promise<void> {
            const before = await droppedClientCount(pool)
            await waitForExpect(
                async () => {
                    const idle = await assertPool.query(
                        `SELECT 1 FROM pg_stat_activity WHERE application_name = $1 AND state = 'idle'`,
                        [DROP_APP]
                    )
                    expect(idle.rowCount).toBeGreaterThan(0)
                },
                2000,
                10
            )
            await terminateDropTestBackends()
            await waitForExpect(async () => expect(await droppedClientCount(pool)).toBeGreaterThan(before), 2000, 10)
        }

        it.each([
            {
                pool: 'manager',
                start: async () => {
                    const dropManager = createManager({ pool: { dbUrl: DROP_DB_URL } })
                    stops.push(() => dropManager.disconnect())
                    await dropManager.connect()
                    return () => dropManager.createJob({ teamId: 1, queueName: QUEUE })
                },
            },
            {
                pool: 'janitor',
                start: async () => {
                    const janitor = createJanitor({ pool: { dbUrl: DROP_DB_URL } })
                    stops.push(() => janitor.stop())
                    await janitor.runOnce()
                    return () => janitor.runOnce()
                },
            },
        ])('$pool survives a dropped idle client and queries on a fresh one', async ({ pool, start }) => {
            const useAgain = await start()
            await dropIdleClients(pool)
            await expect(useAgain()).resolves.toBeDefined()
        })

        it('worker keeps dequeuing and acking after its idle client is dropped', async () => {
            const worker = createWorker(QUEUE, {
                pool: { dbUrl: DROP_DB_URL },
                includeEmptyBatches: false,
                pollDelayMs: 300,
            })
            stops.push(() => worker.disconnect())
            await worker.connect(async (jobs) => {
                await Promise.all(jobs.map((job) => job.ack()))
            })
            await dropIdleClients('worker')

            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            await waitForExpect(async () => expect((await queryJob(id)).status).toBe('completed'), 2000, 10)
        })

        it('counts one drop of a checked-out client once', async () => {
            const pool = createCyclotronPool('worker', { connectionString: DROP_DB_URL })
            const client = await pool.connect()
            stops.push(async () => {
                client.release(true)
                await pool.end()
            })
            const before = await droppedClientCount('worker')
            const ended = new Promise((resolve) => client.once('end', resolve))

            await terminateDropTestBackends()
            await ended

            expect(await droppedClientCount('worker')).toBe(before + 1)
        })

        it('sums the clients of every live pool with one name, and drops a pool once it ends', async () => {
            const clientsOf = async (state: string): Promise<number | undefined> => {
                const metric = register.getSingleMetric('cdp_cyclotron_v2_pg_pool_clients')
                const samples = metric ? (await metric.get()).values : []
                return samples.find((s) => s.labels.pool === 'subscription_matcher' && s.labels.state === state)?.value
            }
            const pools = [1, 2].map(() =>
                createCyclotronPool('subscription_matcher', { connectionString: DB_URL, max: 1 })
            )
            const clients = await Promise.all(pools.map((pool) => pool.connect()))
            let released = false
            const release = (): void => {
                if (!released) {
                    released = true
                    clients.forEach((client) => client.release())
                }
            }
            const ended = new Set<number>()
            const end = async (i: number): Promise<void> => {
                if (!ended.has(i)) {
                    ended.add(i)
                    await pools[i].end()
                }
            }
            stops.push(async () => {
                release()
                await Promise.all(pools.map((_, i) => end(i)))
            })
            const queued = pools.map((pool) => pool.query('SELECT 1'))

            expect(await clientsOf('waiting')).toBe(2)
            expect(await clientsOf('total')).toBe(2)

            release()
            await Promise.all(queued)
            expect(await clientsOf('waiting')).toBe(0)
            expect(await clientsOf('idle')).toBe(2)

            const held = await pools[0].connect()
            const ending = end(0)
            expect(await clientsOf('total')).toBe(1)
            held.release()
            await ending
        })

        it('a check-in on a dropped client commits nothing, and the janitor hands the job back once', async () => {
            const id = await manager.createJob({ teamId: 1, queueName: QUEUE })
            const worker = createWorker(QUEUE, { pool: { dbUrl: DROP_DB_URL } })
            stops.push(() => worker.disconnect())
            const [job] = await dequeueOneBatch(worker)

            const holder = await assertPool.connect()
            try {
                await holder.query('BEGIN')
                await holder.query('SELECT id FROM cyclotron_jobs WHERE id = $1 FOR UPDATE', [id])
                const checkIn = expect(
                    job.bulkCreateAndCheckIn({
                        newJobs: [{ teamId: 1, queueName: QUEUE }],
                        selfDisposition: { kind: 'ack' },
                    })
                ).rejects.toThrow()
                await waitForExpect(
                    async () => {
                        const waiting = await assertPool.query(
                            `SELECT 1 FROM pg_stat_activity WHERE application_name = $1 AND wait_event_type = 'Lock'`,
                            [DROP_APP]
                        )
                        expect(waiting.rowCount).toBeGreaterThan(0)
                    },
                    2000,
                    10
                )
                await terminateDropTestBackends()
                await checkIn
            } finally {
                await holder.query('ROLLBACK')
                holder.release()
            }

            expect(await totalJobCount()).toBe(1)
            expect((await queryJob(id)).status).toBe('running')

            const janitor = createJanitor()
            stops.push(() => janitor.stop())
            await janitor.runOnce()
            const retried = await dequeueOneBatch(worker)
            expect(retried.map((j) => j.id)).toEqual([id])
        })
    })
})
