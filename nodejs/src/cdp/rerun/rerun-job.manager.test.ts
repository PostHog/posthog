import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { parseJSON } from '~/common/utils/json-parse'

import { RerunJobManager } from './rerun-job.manager'
import { RERUN_QUEUE_NAME, RerunJobState } from './rerun-job.types'

const DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const TEST_MAX_COUNT = 1000

describe('RerunJobManager', () => {
    let assertPool: Pool
    let manager: RerunJobManager

    beforeAll(async () => {
        assertPool = new Pool({ connectionString: DB_URL })
        manager = new RerunJobManager({ dbUrl: DB_URL, maxCount: TEST_MAX_COUNT })
        await manager.connect()
    })

    afterAll(async () => {
        await manager.disconnect()
        await assertPool.end()
    })

    beforeEach(async () => {
        await assertPool.query('DELETE FROM cyclotron_jobs WHERE queue_name = $1', [RERUN_QUEUE_NAME])
    })

    interface RawJobRow {
        id: string
        team_id: number
        function_id: string | null
        queue_name: string
        status: string
        state: Buffer | null
    }

    const queryJob = async (id: string): Promise<RawJobRow> => {
        const res = await assertPool.query<RawJobRow>('SELECT * FROM cyclotron_jobs WHERE id = $1', [id])
        expect(res.rows).toHaveLength(1)
        return res.rows[0]
    }

    const fetchState = (row: RawJobRow): RerunJobState => {
        expect(row.state).not.toBeNull()
        return parseJSON(row.state!.toString('utf8')) as RerunJobState
    }

    const baseFilter = {
        window_start: '2026-05-01T00:00:00Z',
        window_end: '2026-05-10T00:00:00Z',
    }

    it('enqueues a wrapper job on the rerun queue with correct identity columns', async () => {
        const functionId = uuidv7()
        const ids = ['inv-1', 'inv-2', 'inv-3']

        const jobId = await manager.enqueue(42, 'hog_function', functionId, {
            filter: { ...baseFilter, invocation_ids: ids },
        })

        const row = await queryJob(jobId)
        expect(row.queue_name).toBe(RERUN_QUEUE_NAME)
        expect(row.status).toBe('available')
        expect(row.team_id).toBe(42)
        // function_id on the wrapper job lets metrics group it alongside the
        // invocations it spawns.
        expect(row.function_id).toBe(functionId)
    })

    it('serializes the request shape into state with a window-relative cursor stub', async () => {
        const functionId = uuidv7()
        const ids = ['a', 'b', 'c']

        const jobId = await manager.enqueue(7, 'hog_function', functionId, {
            filter: { ...baseFilter, invocation_ids: ids },
        })

        const state = fetchState(await queryJob(jobId))
        expect(state.function_kind).toBe('hog_function')
        expect(state.function_id).toBe(functionId)
        expect(state.request.filter.invocation_ids).toEqual(ids)
        expect(state.request.filter.window_start).toBe(baseFilter.window_start)
        expect(state.progress).toEqual({
            queued: 0,
            skipped: 0,
            // undefined cursor signals "start from the top of the window".
            cursor: undefined,
            done: false,
        })
    })

    it('trims oversized invocation_ids lists to the server-side cap', async () => {
        const ids = Array.from({ length: TEST_MAX_COUNT + 50 }, (_, i) => `id-${i}`)

        const jobId = await manager.enqueue(1, 'hog_function', uuidv7(), {
            filter: { ...baseFilter, invocation_ids: ids },
        })

        const state = fetchState(await queryJob(jobId))
        expect(state.request.filter.invocation_ids).toHaveLength(TEST_MAX_COUNT)
    })

    it('serializes a window-only request (no invocation_ids) with undefined cursor', async () => {
        const filter = {
            ...baseFilter,
            status: ['failed' as const],
            error_kind: ['http_5xx'],
            max_attempts: 3,
            max_count: 500,
        }

        const jobId = await manager.enqueue(3, 'hog_flow', uuidv7(), { filter })

        const state = fetchState(await queryJob(jobId))
        expect(state.function_kind).toBe('hog_flow')
        expect(state.request.filter).toMatchObject(filter)
        expect(state.request.filter.invocation_ids).toBeUndefined()
        expect(state.progress.cursor).toBeUndefined()
        expect(state.progress.done).toBe(false)
    })

    it('rejects a window longer than the TTL (30 days)', async () => {
        await expect(
            manager.enqueue(1, 'hog_function', uuidv7(), {
                filter: {
                    window_start: '2026-01-01T00:00:00Z',
                    window_end: '2026-12-31T00:00:00Z',
                },
            })
        ).rejects.toThrow(/cannot exceed 30 days/i)
    })

    it('rejects when window_end is before window_start', async () => {
        await expect(
            manager.enqueue(1, 'hog_function', uuidv7(), {
                filter: { window_start: '2026-05-10T00:00:00Z', window_end: '2026-05-01T00:00:00Z' },
            })
        ).rejects.toThrow(/window_end must be after window_start/i)
    })

    it('returns a uuidv7 for the job id', async () => {
        const jobId = await manager.enqueue(1, 'hog_function', uuidv7(), {
            filter: { ...baseFilter, invocation_ids: ['x'] },
        })
        // uuidv7 conforms to the standard UUID format
        expect(jobId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/)
    })
})
