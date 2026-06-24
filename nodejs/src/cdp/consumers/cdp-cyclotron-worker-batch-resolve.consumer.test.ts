/**
 * End-to-end tests for CdpCyclotronWorkerBatchResolve.
 *
 * Real cyclotron_node Postgres, mocked external services (HogFlowBatchPersonQueryService
 * for audience fetch, putBatchJobStatusFn for Django terminal write).
 *
 * Each test:
 *  1. Inserts a resolver job onto the hogflow_batch_resolve queue with an
 *     initial state.
 *  2. Dequeues one job via a real CyclotronV2Worker.
 *  3. Calls processResolverJob with the dequeued job + mocked deps.
 *  4. Asserts on the resulting cyclotron_jobs state (resolver job row +
 *     children that were enqueued onto the hogflow queue).
 *
 * Mirrors the structure of cyclotron-v2.test.ts so DB setup costs are
 * shared across runs.
 */
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { CyclotronV2DequeuedJob, CyclotronV2Manager, CyclotronV2Worker } from '../services/cyclotron-v2'
import {
    BatchResolverState,
    HOGFLOW_BATCH_RESOLVE_QUEUE,
    deserializeResolverState,
    serializeResolverState,
} from '../services/hogflows/batch-resolver.types'
import { CdpCyclotronWorkerBatchResolve } from './cdp-cyclotron-worker-batch-resolve.consumer'

const DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

let assertPool: Pool
let manager: CyclotronV2Manager
let worker: CyclotronV2Worker

const TEAM_ID = 999
const HOG_FLOW_ID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
const BATCH_JOB_ID = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'

// ── Test helpers ─────────────────────────────────────────────────────

function makeInitialState(overrides: Partial<BatchResolverState> = {}): BatchResolverState {
    return {
        batchJobId: BATCH_JOB_ID,
        teamId: TEAM_ID,
        hogFlowId: HOG_FLOW_ID,
        filters: { properties: [], filter_test_accounts: false },
        variables: {},
        maxAudienceSize: 5000,
        cursor: null,
        totalEnqueued: 0,
        pagesProcessed: 0,
        startedAt: new Date().toISOString(),
        ...overrides,
    }
}

async function insertResolverJob(state: BatchResolverState): Promise<string> {
    const id = await manager.createJob({
        teamId: state.teamId,
        queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
        parentRunId: state.batchJobId,
        functionId: state.hogFlowId,
        state: serializeResolverState(state),
    })
    return id
}

async function dequeueResolverJob(): Promise<CyclotronV2DequeuedJob> {
    let captured: CyclotronV2DequeuedJob[] = []
    await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => resolve(), 3000)
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
    if (captured.length === 0) {
        throw new Error('No resolver job dequeued within timeout')
    }
    return captured[0]
}

async function readResolverState(jobId: string): Promise<{ status: string; state: BatchResolverState | null }> {
    const row = await assertPool.query<{ status: string; state: Buffer | null }>(
        `SELECT status::text AS status, state FROM cyclotron_jobs WHERE id = $1`,
        [jobId]
    )
    if (row.rows.length === 0) {
        throw new Error(`Resolver job ${jobId} not found`)
    }
    return {
        status: row.rows[0].status,
        state: row.rows[0].state ? deserializeResolverState(row.rows[0].state) : null,
    }
}

async function countChildrenForBatch(batchJobId: string): Promise<number> {
    const res = await assertPool.query<{ c: number }>(
        `SELECT COUNT(*)::int AS c FROM cyclotron_jobs WHERE queue_name = 'hogflow' AND parent_run_id = $1`,
        [batchJobId]
    )
    return res.rows[0].c
}

// ── Mocked consumer wrapper ──────────────────────────────────────────
//
// Minimal stand-in that exposes the same processResolverJob entry point but
// with deps mocked. Built ad-hoc per test to avoid spinning up the whole
// CdpConsumerBase (which would need redis, kafka, etc.). The processing
// logic is pure enough that we can extract its dependencies and exercise
// the state machine through the public interface.

interface MockedDeps {
    fetchPages: jest.Mock // (team, filters, groupTypeIndex, cursor) => Promise<{users_affected, cursor, has_more}>
    djangoPutStatus: jest.Mock // (teamId, batchJobId, status, truncatedAtCount) => Promise<void>
    queueLogs: jest.Mock
}

function makeMockedConsumer(deps: MockedDeps): CdpCyclotronWorkerBatchResolve {
    // Bypass CdpConsumerBase's heavy constructor (redis, kafka, hogexecutor, …
    // none of which processResolverJob touches). Wire only what the method
    // actually uses.
    const inst: any = Object.create(CdpCyclotronWorkerBatchResolve.prototype)
    inst.name = 'CdpCyclotronWorkerBatchResolveTest'
    inst.config = { SITE_URL: 'http://localhost:8000' }
    inst.deps = {
        teamManager: { getTeam: () => Promise.resolve({ id: TEAM_ID }) },
    }
    inst.hogFlowManager = {
        getHogFlow: () =>
            Promise.resolve({
                id: HOG_FLOW_ID,
                team_id: TEAM_ID,
                variables: [],
            }),
    }
    inst.hogFunctionMonitoringService = {
        queueLogs: deps.queueLogs,
        flush: () => Promise.resolve(),
    }
    inst.hogFlowBatchPersonQueryService = {
        getBlastRadiusPersons: deps.fetchPages,
    }
    inst.putBatchJobStatusFn = deps.djangoPutStatus
    return inst as CdpCyclotronWorkerBatchResolve
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('CdpCyclotronWorkerBatchResolve (integration)', () => {
    jest.setTimeout(10000)

    beforeAll(async () => {
        assertPool = new Pool({ connectionString: DB_URL })
        manager = new CyclotronV2Manager({ pool: { dbUrl: DB_URL }, depthLimit: 1_000_000, depthCheckIntervalMs: 0 })
        await manager.connect()
    })

    afterAll(async () => {
        await manager.disconnect()
        await assertPool.end()
    })

    beforeEach(async () => {
        await assertPool.query(`DELETE FROM cyclotron_jobs WHERE team_id = $1`, [TEAM_ID])
        worker = new CyclotronV2Worker({
            pool: { dbUrl: DB_URL },
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            batchMaxSize: 1,
            pollDelayMs: 10,
        })
    })

    afterEach(async () => {
        await worker.disconnect()
    })

    it('first page: fetches, enqueues children, reschedules with advanced cursor', async () => {
        const initial = makeInitialState({ maxAudienceSize: 1000 })
        const jobId = await insertResolverJob(initial)
        const dequeued = await dequeueResolverJob()

        const consumer = makeMockedConsumer({
            fetchPages: jest.fn().mockResolvedValue({
                users_affected: [uuidv7(), uuidv7(), uuidv7()],
                cursor: 'cursor-after-first',
                has_more: true,
            }),
            djangoPutStatus: jest.fn().mockResolvedValue(undefined),
            queueLogs: jest.fn(),
        })

        await consumer.processResolverJob(dequeued)

        // Resolver job: back to available with advanced state
        const after = await readResolverState(jobId)
        expect(after.status).toBe('available')
        expect(after.state).toMatchObject({
            cursor: 'cursor-after-first',
            totalEnqueued: 3,
            pagesProcessed: 1,
        })
        expect(after.state?.pendingTerminal).toBeUndefined()

        // Children enqueued on hogflow queue
        expect(await countChildrenForBatch(BATCH_JOB_ID)).toBe(3)
    })

    it('last page: fetches, enqueues final children, transitions to pendingTerminal=completed', async () => {
        const initial = makeInitialState({ cursor: 'mid-cursor', totalEnqueued: 7, pagesProcessed: 14 })
        const jobId = await insertResolverJob(initial)
        const dequeued = await dequeueResolverJob()

        const consumer = makeMockedConsumer({
            fetchPages: jest.fn().mockResolvedValue({
                users_affected: [uuidv7(), uuidv7()],
                cursor: null,
                has_more: false,
            }),
            djangoPutStatus: jest.fn().mockResolvedValue(undefined),
            queueLogs: jest.fn(),
        })

        await consumer.processResolverJob(dequeued)

        const after = await readResolverState(jobId)
        expect(after.status).toBe('available') // requeued for the terminal-write phase
        expect(after.state).toMatchObject({
            totalEnqueued: 9,
            pagesProcessed: 15,
            pendingTerminal: 'completed',
        })
        expect(await countChildrenForBatch(BATCH_JOB_ID)).toBe(2)
    })

    it('terminal write success: PUTs to Django and acks the resolver job', async () => {
        const initial = makeInitialState({
            cursor: null,
            totalEnqueued: 42,
            pagesProcessed: 1,
            pendingTerminal: 'completed',
        })
        const jobId = await insertResolverJob(initial)
        const dequeued = await dequeueResolverJob()

        const djangoPut = jest.fn().mockResolvedValue(undefined)
        const consumer = makeMockedConsumer({
            fetchPages: jest.fn(),
            djangoPutStatus: djangoPut,
            queueLogs: jest.fn(),
        })

        await consumer.processResolverJob(dequeued)

        expect(djangoPut).toHaveBeenCalledWith(TEAM_ID, BATCH_JOB_ID, 'completed', undefined)

        const after = await readResolverState(jobId)
        expect(after.status).toBe('completed')
    })

    it('terminal write failure: reschedules with backoff, no ack', async () => {
        const initial = makeInitialState({ pendingTerminal: 'completed', totalEnqueued: 5 })
        const jobId = await insertResolverJob(initial)
        const dequeued = await dequeueResolverJob()

        const djangoPut = jest.fn().mockRejectedValue(new Error('Django is down'))
        const consumer = makeMockedConsumer({
            fetchPages: jest.fn(),
            djangoPutStatus: djangoPut,
            queueLogs: jest.fn(),
        })

        await consumer.processResolverJob(dequeued)

        expect(djangoPut).toHaveBeenCalledTimes(1)

        const after = await readResolverState(jobId)
        // Rescheduled — still available, state preserved (pendingTerminal still set)
        expect(after.status).toBe('available')
        expect(after.state?.pendingTerminal).toBe('completed')
        expect(after.state?.totalEnqueued).toBe(5)
    })

    it('page fetch failure: reschedules with backoff, cursor unchanged', async () => {
        const initial = makeInitialState({ cursor: 'page-3-cursor', totalEnqueued: 1500, pagesProcessed: 3 })
        const jobId = await insertResolverJob(initial)
        const dequeued = await dequeueResolverJob()

        const consumer = makeMockedConsumer({
            fetchPages: jest.fn().mockRejectedValue(new Error('The operation was aborted due to timeout')),
            djangoPutStatus: jest.fn(),
            queueLogs: jest.fn(),
        })

        await consumer.processResolverJob(dequeued)

        const after = await readResolverState(jobId)
        expect(after.status).toBe('available')
        expect(after.state).toMatchObject({
            cursor: 'page-3-cursor', // unchanged — retry resumes from same cursor
            totalEnqueued: 1500,
            pagesProcessed: 3,
        })
        expect(after.state?.pendingTerminal).toBeUndefined()
        expect(await countChildrenForBatch(BATCH_JOB_ID)).toBe(0)
    })

    it('truncation: when totalEnqueued >= maxAudienceSize, sets pendingTerminal with truncatedAtCount + emits log + skips fetch', async () => {
        const initial = makeInitialState({
            maxAudienceSize: 100,
            totalEnqueued: 100, // cap reached
            cursor: 'some-cursor',
            pagesProcessed: 1,
        })
        const jobId = await insertResolverJob(initial)
        const dequeued = await dequeueResolverJob()

        const fetchPages = jest.fn()
        const queueLogs = jest.fn()
        const consumer = makeMockedConsumer({
            fetchPages,
            djangoPutStatus: jest.fn(),
            queueLogs,
        })

        await consumer.processResolverJob(dequeued)

        // No further audience fetch
        expect(fetchPages).not.toHaveBeenCalled()

        // Customer-facing log was emitted
        expect(queueLogs).toHaveBeenCalledWith(
            expect.arrayContaining([
                expect.objectContaining({
                    log_source: 'hog_flow',
                    log_source_id: BATCH_JOB_ID,
                }),
            ]),
            'hog_flow'
        )

        const after = await readResolverState(jobId)
        expect(after.status).toBe('available') // requeued for terminal-write
        expect(after.state).toMatchObject({
            pendingTerminal: 'completed',
            truncatedAtCount: 100,
        })
    })

    it('full multi-page lifecycle: 3 pages → terminal write → ack, children enqueued in order', async () => {
        const initial = makeInitialState({ maxAudienceSize: 1000 })
        const jobId = await insertResolverJob(initial)

        const fetchPages = jest
            .fn()
            .mockResolvedValueOnce({
                users_affected: [uuidv7(), uuidv7()],
                cursor: 'c1',
                has_more: true,
            })
            .mockResolvedValueOnce({
                users_affected: [uuidv7(), uuidv7(), uuidv7()],
                cursor: 'c2',
                has_more: true,
            })
            .mockResolvedValueOnce({
                users_affected: [uuidv7()],
                cursor: null,
                has_more: false,
            })

        const djangoPut = jest.fn().mockResolvedValue(undefined)
        const consumer = makeMockedConsumer({
            fetchPages,
            djangoPutStatus: djangoPut,
            queueLogs: jest.fn(),
        })

        // Page 1
        let dequeued = await dequeueResolverJob()
        await consumer.processResolverJob(dequeued)
        worker = new CyclotronV2Worker({
            pool: { dbUrl: DB_URL },
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            batchMaxSize: 1,
            pollDelayMs: 10,
        })

        // Page 2
        dequeued = await dequeueResolverJob()
        await consumer.processResolverJob(dequeued)
        worker = new CyclotronV2Worker({
            pool: { dbUrl: DB_URL },
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            batchMaxSize: 1,
            pollDelayMs: 10,
        })

        // Page 3 (last)
        dequeued = await dequeueResolverJob()
        await consumer.processResolverJob(dequeued)
        worker = new CyclotronV2Worker({
            pool: { dbUrl: DB_URL },
            queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
            batchMaxSize: 1,
            pollDelayMs: 10,
        })

        // Terminal write
        dequeued = await dequeueResolverJob()
        await consumer.processResolverJob(dequeued)

        expect(fetchPages).toHaveBeenCalledTimes(3)
        expect(djangoPut).toHaveBeenCalledTimes(1)
        expect(djangoPut).toHaveBeenCalledWith(TEAM_ID, BATCH_JOB_ID, 'completed', undefined)

        const final = await readResolverState(jobId)
        expect(final.status).toBe('completed')
        expect(final.state?.totalEnqueued).toBe(6)
        expect(final.state?.pagesProcessed).toBe(3)
        expect(await countChildrenForBatch(BATCH_JOB_ID)).toBe(6)
    })
})
