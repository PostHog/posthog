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
    let hasInFlightWrapperMock: jest.Mock
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
        hasInFlightWrapperMock = jest.fn().mockResolvedValue(false)
        clickhouse = { query: queryMock } as unknown as ClickHouseClient
        rerunManager = {
            enqueue: enqueueMock,
            hasInFlightWrapper: hasInFlightWrapperMock,
        } as unknown as RerunJobManager
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

    it('skips a group that already has an in-flight rerun wrapper', async () => {
        mockDiscovered([
            { team_id: '1', function_kind: 'hog_flow', function_id: 'fn-a', pending: '5' },
            { team_id: '2', function_kind: 'hog_flow', function_id: 'fn-b', pending: '3' },
        ])
        // fn-a already has an outstanding wrapper; fn-b does not. Without the
        // in-flight guard both would enqueue, piling up duplicate wrappers when a
        // downstream rerun-worker outage keeps a group discoverable every tick.
        hasInFlightWrapperMock.mockImplementation((_teamId: number, functionId: string) =>
            Promise.resolve(functionId === 'fn-a')
        )

        const result = await worker.runOnce()

        expect(result).toEqual({ groups: 2, enqueued: 1 })
        expect(enqueueMock).toHaveBeenCalledTimes(1)
        expect(enqueueMock).toHaveBeenCalledWith(2, 'hog_flow', 'fn-b', expect.anything())
    })

    // The discovery SQL itself is proven end-to-end in poison-pill-autodrain-e2e —
    // this only guards the bound params (window bounds serialized to the CH DateTime
    // format, attempts cap, batch) that the query is templated with.
    it('binds discovery to the window, attempts cap and batch from config', async () => {
        mockDiscovered([])

        await worker.runOnce()

        expect(queryMock.mock.calls[0][0].query_params).toMatchObject({
            error_kind: JANITOR_POISON_PILL_ERROR_KIND,
            max_attempts: 3,
            group_batch: 100,
            window_start: '2026-07-15 12:00:00.000',
            window_end: '2026-07-16 12:00:00.000',
        })
    })

    // The autodrain is co-located in the janitor process, and serviceLoaders are
    // awaited together — a rejected start() would fail the shared pod's boot. A
    // ClickHouse failure on the immediate first tick must therefore not reject
    // start(); the interval is already scheduled so the next tick retries.
    it('start() does not reject when the first tick fails, so it cannot crash the janitor pod', async () => {
        queryMock.mockRejectedValue(new Error('clickhouse down at boot'))

        await expect(worker.start()).resolves.toBeUndefined()
        expect(worker.isRunning()).toBe(true)

        worker.stop()
    })
})
