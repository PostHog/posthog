import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { performQuery, pollForResults, queryExportContext, waitForPageVisible } from '~/queries/query'
import { EventsQuery, HogQLQuery, NodeKind, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { setLatestVersionsOnQuery } from './utils'

describe('query', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const data = (await request.json()) as any
                    if (data.query?.kind === 'HogQLQuery') {
                        return [
                            200,
                            { results: [], clickhouse: 'clickhouse string', hogql: 'hogql string', is_cached: false },
                        ]
                    }
                    if (data.query?.kind === 'WebStatsTableQuery') {
                        return [
                            200,
                            {
                                results: [],
                                is_cached: false,
                                preComputeStrategy: 'lazy_precompute',
                                preComputeStale: true,
                            },
                        ]
                    }
                    if (data.query?.kind === 'EventsQuery' && data.query.select[0] === 'error') {
                        return [500, { detail: 'error' }]
                    }
                    return [200, {}]
                },
            },
        })
        initKeaTests()
    })

    it('can generate events table export context', () => {
        const q: EventsQuery = {
            kind: NodeKind.EventsQuery,
            select: [
                '*',
                'event',
                'person',
                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                'properties.$lib',
                'timestamp',
            ],
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Exact,
                    value: 'Chrome',
                },
            ],
            limit: 100,
        }
        const actual = queryExportContext(q, {}, false)
        expect(actual).toEqual({
            source: {
                kind: 'EventsQuery',
                limit: 100,
                properties: [
                    {
                        key: '$browser',
                        operator: 'exact',
                        type: 'event',
                        value: 'Chrome',
                    },
                ],
                select: [
                    '*',
                    'event',
                    'person',
                    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                    'properties.$lib',
                    'timestamp',
                ],
            },
        })
    })

    it('emits an event when a query is run', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: EventsQuery = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['timestamp'],
            limit: 100,
        })
        captureSpy.mockClear()
        await performQuery(q)
        const queryCompletedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
        expect(queryCompletedCalls).toHaveLength(1)
        expect(queryCompletedCalls[0][1]).toMatchObject({ query: q, duration: expect.any(Number) })
    })

    it('emits a specific event on a HogQLQuery', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: HogQLQuery = setLatestVersionsOnQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select * from events',
        })
        captureSpy.mockClear()
        await performQuery(q)
        const queryCompletedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
        expect(queryCompletedCalls).toHaveLength(1)
        expect(queryCompletedCalls[0][1]).toMatchObject({
            query: q,
            duration: expect.any(Number),
            clickhouse_sql: expect.any(String),
            is_cached: false,
        })
    })

    it('captures precompute strategy and staleness from web analytics responses', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q = setLatestVersionsOnQuery({
            kind: NodeKind.WebStatsTableQuery,
            breakdownBy: WebStatsBreakdown.Page,
            properties: [],
        }) as any
        captureSpy.mockClear()
        await performQuery(q)
        const queryCompletedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
        expect(queryCompletedCalls).toHaveLength(1)
        expect(queryCompletedCalls[0][1]).toMatchObject({
            precompute_strategy: 'lazy_precompute',
            precompute_stale: true,
        })
    })

    it('emits an event when a query errors', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: EventsQuery = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['error'],
            limit: 100,
        })
        captureSpy.mockClear()
        await expect(async () => {
            await performQuery(q)
        }).rejects.toThrow(ApiError)

        const queryFailedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query failed')
        expect(queryFailedCalls).toHaveLength(1)
        expect(queryFailedCalls[0][1]).toMatchObject({
            query: q,
            duration: expect.any(Number),
            error_status: 500,
            error_code: null,
        })
        // Raw error text must stay out of telemetry
        expect(queryFailedCalls[0][1]).not.toHaveProperty('error_message')
    })

    it('does not emit a query failed event when the request is aborted', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: HogQLQuery = setLatestVersionsOnQuery({
            kind: NodeKind.HogQLQuery,
            query: 'select * from events',
        })
        captureSpy.mockClear()
        const controller = new AbortController()
        controller.abort()
        await expect(performQuery(q, { signal: controller.signal })).rejects.toThrow()

        const queryFailedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query failed')
        expect(queryFailedCalls).toHaveLength(0)
    })

    describe('waitForPageVisible', () => {
        const originalVisibilityState = document.visibilityState

        afterEach(() => {
            Object.defineProperty(document, 'visibilityState', { value: originalVisibilityState, configurable: true })
        })

        it('resolves immediately when page is visible', async () => {
            Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
            await expect(waitForPageVisible()).resolves.toBeUndefined()
        })

        it('suspends when page is hidden and resolves when it becomes visible', async () => {
            Object.defineProperty(document, 'visibilityState', {
                value: 'hidden',
                writable: true,
                configurable: true,
            })

            let resolved = false
            const promise = waitForPageVisible().then(() => {
                resolved = true
            })

            await Promise.resolve()
            expect(resolved).toBe(false)

            Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
            document.dispatchEvent(new Event('visibilitychange'))

            await promise
            expect(resolved).toBe(true)
        })

        it('rejects with AbortError when signal is already aborted', async () => {
            Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
            const controller = new AbortController()
            controller.abort()

            await expect(waitForPageVisible(controller.signal)).rejects.toThrow('Aborted')
        })

        it('rejects with AbortError when signal aborts while waiting', async () => {
            Object.defineProperty(document, 'visibilityState', {
                value: 'hidden',
                writable: true,
                configurable: true,
            })
            const controller = new AbortController()

            const promise = waitForPageVisible(controller.signal)

            await Promise.resolve()
            controller.abort()

            await expect(promise).rejects.toThrow('Aborted')
        })

        it('resolves immediately when document is undefined (SSR)', async () => {
            const originalDocument = globalThis.document
            // @ts-expect-error -- simulating SSR by removing document
            delete globalThis.document

            try {
                await expect(waitForPageVisible()).resolves.toBeUndefined()
            } finally {
                globalThis.document = originalDocument
            }
        })
    })

    describe('pollForResults and backgrounded tabs', () => {
        const originalVisibilityState = document.visibilityState

        afterEach(() => {
            Object.defineProperty(document, 'visibilityState', { value: originalVisibilityState, configurable: true })
            jest.restoreAllMocks()
        })

        it('does not count time spent hidden against the poll deadline', async () => {
            Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })

            let now = 0
            jest.spyOn(performance, 'now').mockImplementation(() => now)

            jest.spyOn(api.queryStatus, 'get')
                .mockResolvedValueOnce({ query_status: { complete: false } } as any)
                .mockResolvedValueOnce({ query_status: { complete: true, results: ['ok'] } } as any)

            const promise = pollForResults('test-query-id', undefined, () => {
                // Fires right after the first (incomplete) poll, before the loop rechecks its
                // deadline for the next one. Simulate the tab backgrounding for longer than the
                // whole poll deadline (10m6s) right here: a wall-clock deadline would time out on
                // the very next check, even though no polling actually happened during that time.
                Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
                now += 11 * 60 * 1000
                setTimeout(() => {
                    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
                    document.dispatchEvent(new Event('visibilitychange'))
                }, 0)
            })

            await expect(promise).resolves.toMatchObject({ complete: true, results: ['ok'] })
        })
    })

    describe('dropped blocking request recovery', () => {
        const query = { kind: NodeKind.EventsQuery, select: ['*'] } as EventsQuery
        const gatewayTimeout = (): ApiError => new ApiError('upstream request timeout', 504)
        /** A drop, which by definition happens after the request has run long enough to be worth
         * recovering. Anything faster has no record waiting for it. */
        const dropAfterRunningLong = async (): Promise<never> => {
            now += 5 * 60 * 1000
            throw gatewayTimeout()
        }
        const notRecordedYet = (): ApiError =>
            new ApiError('Query not found', 404, undefined, { detail: 'Query not found' })
        let now: number

        beforeEach(() => {
            now = 1_700_000_000_000
            jest.spyOn(Date, 'now').mockImplementation(() => now)
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('sends every blocking request with a client query id', async () => {
            const querySpy = jest.spyOn(api, 'query').mockResolvedValueOnce({ results: [] } as any)

            await performQuery(query, undefined, 'blocking')

            expect(querySpy.mock.calls[0][1]).toMatchObject({ clientQueryId: expect.any(String) })
        })

        it('returns the recorded result once the server finishes a dropped request', async () => {
            const querySpy = jest.spyOn(api, 'query').mockImplementationOnce(dropAfterRunningLong)
            const statusSpy = jest
                .spyOn(api.queryStatus, 'get')
                .mockImplementationOnce(async () => {
                    // Not recorded yet. Jump to just before the deadline so the next poll follows a
                    // short wait instead of the real interval.
                    now += 10 * 60 * 1000 - 10
                    throw notRecordedYet()
                })
                .mockResolvedValueOnce({ query_status: { complete: true, results: { results: ['late'] } } } as any)
            const captureSpy = jest.spyOn(posthog, 'capture')

            await expect(performQuery(query, undefined, 'blocking')).resolves.toMatchObject({ results: ['late'] })

            expect(statusSpy.mock.calls[0][0]).toBe(querySpy.mock.calls[0][1]?.clientQueryId)
            const completed = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
            expect(completed[0][1]).toMatchObject({ recovered_after_drop: true })
        })

        it('surfaces the recorded error of a dropped request without waiting', async () => {
            jest.spyOn(api, 'query').mockImplementationOnce(dropAfterRunningLong)
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(
                new ApiError('failed', 400, undefined, {
                    query_status: { error_message: 'Try changing the time range', error_code: 'too_wide' },
                })
            )

            await expect(performQuery(query, undefined, 'blocking')).rejects.toMatchObject({
                status: 400,
                detail: 'Try changing the time range',
                code: 'too_wide',
            })
        })

        it('gives up with the original error when nothing is recorded by the deadline', async () => {
            jest.spyOn(api, 'query').mockImplementationOnce(dropAfterRunningLong)
            const statusSpy = jest.spyOn(api.queryStatus, 'get').mockImplementation(async () => {
                now += 10 * 60 * 1000
                throw notRecordedYet()
            })
            const captureSpy = jest.spyOn(posthog, 'capture')

            await expect(performQuery(query, undefined, 'blocking')).rejects.toMatchObject({ status: 504 })

            expect(statusSpy).toHaveBeenCalledTimes(1)
            const failed = captureSpy.mock.calls.filter((call) => call[0] === 'query failed')
            expect(failed[0][1]).toMatchObject({ drop_recovery_attempted: true, error_status: 504 })
        })

        it('waits for a record written past the time the request itself was allowed to run', async () => {
            jest.spyOn(api, 'query').mockImplementationOnce(async () => {
                // The gateway drops the request a minute in, while the query keeps running.
                now += 60 * 1000
                throw gatewayTimeout()
            })
            jest.spyOn(api.queryStatus, 'get')
                .mockImplementationOnce(async () => {
                    // The server writes the record just short of ten minutes after the drop, which
                    // is past the ten minutes the query itself was allowed to spend in ClickHouse.
                    now += 10 * 60 * 1000 - 10
                    throw notRecordedYet()
                })
                .mockResolvedValueOnce({ query_status: { complete: true, results: { results: ['late'] } } } as any)

            await expect(performQuery(query, undefined, 'blocking')).resolves.toMatchObject({ results: ['late'] })
        })

        it('recovers a dropped force_cache request, which the endpoint runs when the cache is stale', async () => {
            jest.spyOn(api, 'query').mockImplementationOnce(dropAfterRunningLong)
            const statusSpy = jest
                .spyOn(api.queryStatus, 'get')
                .mockResolvedValueOnce({ query_status: { complete: true, results: { results: ['late'] } } } as any)

            await expect(performQuery(query, undefined, 'force_cache')).resolves.toMatchObject({
                results: ['late'],
            })

            expect(statusSpy).toHaveBeenCalledTimes(1)
        })

        it('does not follow up on a timeout the app answered with itself', async () => {
            // A ClickHouse timeout is a 504 too, and the failure breaker replays it at once, so
            // there is no run left to wait for and no record to wait for it under.
            jest.spyOn(api, 'query').mockRejectedValueOnce(
                new ApiError('timed out', 504, undefined, {
                    detail: 'Query has hit the max execution time before completing.',
                })
            )
            const statusSpy = jest.spyOn(api.queryStatus, 'get')

            await expect(performQuery(query, undefined, 'blocking')).rejects.toMatchObject({ status: 504 })

            expect(statusSpy).not.toHaveBeenCalled()
        })

        it('does not follow up on a 504 that arrived too fast to have left a record', async () => {
            // The server records a blocking outcome only after the request has run a while, so a
            // 504 that arrives at once has nothing to wait for however it was produced.
            jest.spyOn(api, 'query').mockRejectedValueOnce(gatewayTimeout())
            const statusSpy = jest.spyOn(api.queryStatus, 'get')

            await expect(performQuery(query, undefined, 'blocking')).rejects.toMatchObject({ status: 504 })

            expect(statusSpy).not.toHaveBeenCalled()
        })

        it('does not follow up on a failed async submission', async () => {
            jest.spyOn(api, 'query').mockRejectedValueOnce(gatewayTimeout())
            const statusSpy = jest.spyOn(api.queryStatus, 'get')

            await expect(performQuery(query, undefined, 'async')).rejects.toMatchObject({ status: 504 })

            expect(statusSpy).not.toHaveBeenCalled()
        })
    })

    describe('pollForResults error message parsing', () => {
        it('prefers the structured error_code from the query status over one parsed from the message', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: 'This query ran out of memory before it could finish',
                        error_code: 'clickhouse_memory_limit_exceeded',
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'This query ran out of memory before it could finish',
                code: 'clickhouse_memory_limit_exceeded',
            })
        })

        it('parses ErrorDetail list format and extracts message and code', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message:
                            "[ErrorDetail(string='Query exceeded memory limit', code='memory_limit_exceeded')]",
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'Query exceeded memory limit',
                code: 'memory_limit_exceeded',
            })
        })

        it('parses ErrorDetail single format and extracts message and code', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: "ErrorDetail(string='Database connection failed', code='db_error')",
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'Database connection failed',
                code: 'db_error',
            })
        })

        it('preserves original message when not in ErrorDetail format', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: 'Simple error message',
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'Simple error message',
            })
        })

        it('preserves a detail-only API error', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    detail: 'This managed warehouse connection is no longer available. Select a source and run the query again.',
                    code: 'managed_warehouse_connection_unavailable',
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: 'This managed warehouse connection is no longer available. Select a source and run the query again.',
                code: 'managed_warehouse_connection_unavailable',
            })
        })

        it('handles undefined error message', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {},
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: '',
            })
        })

        it('handles non-string error message', async () => {
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce({
                data: {
                    query_status: {
                        error_message: { nested: 'object' },
                    },
                },
            })

            await expect(pollForResults('test-query-id')).rejects.toMatchObject({
                detail: { nested: 'object' },
            })
        })
    })
})
