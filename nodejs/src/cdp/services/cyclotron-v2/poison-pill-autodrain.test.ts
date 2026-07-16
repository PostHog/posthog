import { ClickHouseClient } from '@clickhouse/client'

import { RerunJobManager } from '../../rerun/rerun-job.manager'
import { JANITOR_POISON_PILL_ERROR_KIND } from './janitor'
import { CyclotronPoisonPillAutodrain, CyclotronPoisonPillAutodrainConfig } from './poison-pill-autodrain'

describe('CyclotronPoisonPillAutodrain', () => {
    const NOW = new Date('2026-07-16T12:00:00.000Z')

    const config: CyclotronPoisonPillAutodrainConfig = {
        intervalMs: 60_000,
        windowHours: 24,
        maxAttempts: 3,
        groupBatch: 100,
        maxCountPerGroup: 1000,
    }

    let queryMock: jest.Mock
    let enqueueMock: jest.Mock
    let clickhouse: ClickHouseClient
    let rerunManager: RerunJobManager
    let worker: CyclotronPoisonPillAutodrain

    // Fake ClickHouse client returning canned discovered-group rows. 64-bit ints
    // arrive as strings from JSONEachRow — mirror that so parsing is exercised.
    const mockDiscovered = (rows: object[]): void => {
        queryMock.mockResolvedValue({ json: () => Promise.resolve(rows) })
    }

    beforeEach(() => {
        jest.useFakeTimers({ now: NOW })
        queryMock = jest.fn()
        enqueueMock = jest.fn().mockResolvedValue('job-id')
        clickhouse = { query: queryMock } as unknown as ClickHouseClient
        rerunManager = { enqueue: enqueueMock } as unknown as RerunJobManager
        worker = new CyclotronPoisonPillAutodrain(clickhouse, rerunManager, config)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('enqueues one rerun per discovered group with the poison-pill filter', async () => {
        mockDiscovered([
            { team_id: '1', function_kind: 'hog_flow', function_id: 'fn-a', pending: '5' },
            { team_id: '2', function_kind: 'hog_function', function_id: 'fn-b', pending: '2' },
        ])

        const result = await worker.runOnce()

        expect(result).toEqual({ groups: 2, enqueued: 2 })
        expect(enqueueMock).toHaveBeenCalledTimes(2)

        const expectedFilter = {
            window_start: '2026-07-15T12:00:00.000Z',
            window_end: '2026-07-16T12:00:00.000Z',
            status: ['failed'],
            error_kind: [JANITOR_POISON_PILL_ERROR_KIND],
            max_attempts: 3,
            max_count: 1000,
        }
        // team_id parsed to a number; window is exactly windowHours wide and ends now.
        expect(enqueueMock).toHaveBeenNthCalledWith(1, 1, 'hog_flow', 'fn-a', { filter: expectedFilter })
        expect(enqueueMock).toHaveBeenNthCalledWith(2, 2, 'hog_function', 'fn-b', { filter: expectedFilter })
    })

    it('enqueues nothing when no groups are discovered', async () => {
        mockDiscovered([])

        const result = await worker.runOnce()

        expect(result).toEqual({ groups: 0, enqueued: 0 })
        expect(enqueueMock).not.toHaveBeenCalled()
    })

    it('keeps draining the remaining groups when one group fails to enqueue', async () => {
        mockDiscovered([
            { team_id: '1', function_kind: 'hog_flow', function_id: 'fn-a', pending: '5' },
            { team_id: '2', function_kind: 'hog_flow', function_id: 'fn-b', pending: '3' },
            { team_id: '3', function_kind: 'hog_flow', function_id: 'fn-c', pending: '1' },
        ])
        enqueueMock.mockRejectedValueOnce(new Error('cyclotron down'))

        const result = await worker.runOnce()

        // The failing group is counted out but the other two still enqueue.
        expect(result).toEqual({ groups: 3, enqueued: 2 })
        expect(enqueueMock).toHaveBeenCalledTimes(3)
    })

    it('scopes discovery to the not-deleted failed poison-pill predicate under the attempts cap', async () => {
        mockDiscovered([])

        await worker.runOnce()

        const query: string = queryMock.mock.calls[0][0].query
        expect(query).toContain("argMax(status, version) = 'failed'")
        expect(query).toContain('argMax(error_kind, version) = {error_kind:String}')
        expect(query).toContain('argMax(attempts, version) < {max_attempts:UInt8}')
        expect(queryMock.mock.calls[0][0].query_params).toMatchObject({
            error_kind: JANITOR_POISON_PILL_ERROR_KIND,
            max_attempts: 3,
            group_batch: 100,
            window_start: '2026-07-15 12:00:00.000',
            window_end: '2026-07-16 12:00:00.000',
        })
    })
})
