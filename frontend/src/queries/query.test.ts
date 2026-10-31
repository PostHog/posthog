import { HttpResponse } from 'msw'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { NetworkError } from 'lib/api-error'

import { useMocks } from '~/mocks/jest'
import { performQuery, pollForResults, queryExportContext, waitForPageVisible } from '~/queries/query'
import { EventsQuery, HogQLQuery, NodeKind, RefreshType, WebStatsBreakdown } from '~/queries/schema/schema-general'
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
        const querySpy = jest.spyOn(api, 'query')
        const q: EventsQuery = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['timestamp'],
            limit: 100,
        })
        captureSpy.mockClear()
        const onRequestTiming = jest.fn()
        await performQuery(q, { onRequestTiming })
        const queryCompletedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query completed')
        expect(queryCompletedCalls).toHaveLength(1)
        expect(queryCompletedCalls[0][1]).toMatchObject({
            query: q,
            duration: expect.any(Number),
            client_query_id: querySpy.mock.calls.at(-1)?.[1]?.clientQueryId,
            submit_attempts: 1,
            retry_wait_ms: expect.any(Number),
            retry_status: null,
            retry_recovered: false,
            submit_request_timings: [
                expect.objectContaining({
                    request_total_ms: expect.any(Number),
                    time_to_headers_ms: expect.any(Number),
                    body_read_ms: expect.any(Number),
                    json_parse_ms: expect.any(Number),
                    http_status: 200,
                }),
            ],
            time_to_headers_ms: expect.any(Number),
            body_read_ms: expect.any(Number),
            json_parse_ms: expect.any(Number),
            resource_timing_status: 'missing_request_id',
        })
        expect(onRequestTiming).toHaveBeenCalledTimes(1)
        expect(onRequestTiming).toHaveBeenCalledWith(queryCompletedCalls[0][1]?.submit_request_timings?.[0])
        expect(queryCompletedCalls[0][1]).not.toHaveProperty('result_poll_timing')
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

    it('keeps each retry timing on the existing completion event and flattens the final attempt', async () => {
        const requestIds = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222']
        let attempts = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => {
                    const headers = { 'X-Request-ID': requestIds[attempts] }
                    return ++attempts === 1
                        ? HttpResponse.json({ detail: 'temporarily unavailable' }, { status: 502, headers })
                        : HttpResponse.json({ results: [] }, { headers })
                },
            },
        })
        const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
        const query: HogQLQuery = { kind: NodeKind.HogQLQuery, query: 'select 1' }

        await expect(performQuery(query)).resolves.toMatchObject({ results: [] })

        const completed = captureSpy.mock.calls.filter(([event]) => event === 'query completed')
        expect(completed).toHaveLength(1)
        expect(completed[0][1]).toMatchObject({
            submit_attempts: 2,
            submit_request_timings: [
                expect.objectContaining({ http_status: 502, http_request_id: requestIds[0] }),
                expect.objectContaining({ http_status: 200, http_request_id: requestIds[1] }),
            ],
            http_request_id: requestIds[1],
            body_read_ms: expect.any(Number),
        })
    })

    it('records only the poll that returns the completed async result', async () => {
        const pollRequestIds = ['33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444']
        let polls = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    { query_status: { id: 'async-query', complete: false } },
                ],
            },
            get: {
                '/api/environments/:team_id/query/:id': () => {
                    const complete = polls === 1
                    const headers = { 'X-Request-ID': pollRequestIds[polls++] }
                    return HttpResponse.json(
                        { query_status: { id: 'async-query', complete, results: complete ? { results: [] } : null } },
                        { headers }
                    )
                },
            },
        })
        jest.useFakeTimers()
        const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
        const query: HogQLQuery = { kind: NodeKind.HogQLQuery, query: 'select 1' }

        try {
            const promise = performQuery(query, undefined, 'async')
            await jest.advanceTimersByTimeAsync(1000)
            await expect(promise).resolves.toEqual({ results: [] })
        } finally {
            jest.useRealTimers()
        }

        expect(polls).toBe(2)
        const completed = captureSpy.mock.calls.filter(([event]) => event === 'query completed')
        expect(completed).toHaveLength(1)
        expect(completed[0][1]).toMatchObject({
            result_poll_timing: expect.objectContaining({
                http_status: 200,
                http_request_id: pollRequestIds[1],
                body_read_ms: expect.any(Number),
                json_parse_ms: expect.any(Number),
            }),
            result_poll_http_request_id: pollRequestIds[1],
            result_poll_body_read_ms: expect.any(Number),
            result_poll_json_parse_ms: expect.any(Number),
        })
        expect(completed[0][1]?.submit_request_timings).toHaveLength(1)
    })

    it.each([
        [true, 1],
        [undefined, 0],
    ])('when uses_history_table is %s, sends %i history queried events', async (usesHistoryTable, expectedEvents) => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    {
                        results: [],
                        is_cached: false,
                        used_data_warehouse_sources: [
                            {
                                id: 'src-1',
                                source_type: 'Postgres',
                                table_name: 'orders_cdc',
                                uses_history_table: usesHistoryTable,
                            },
                        ],
                    },
                ],
            },
        })
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: HogQLQuery = setLatestVersionsOnQuery({ kind: NodeKind.HogQLQuery, query: 'select * from orders_cdc' })
        captureSpy.mockClear()
        await performQuery(q)
        const historyCalls = captureSpy.mock.calls.filter((call) => call[0] === 'data warehouse history table queried')
        expect(historyCalls).toHaveLength(expectedEvents)
        if (expectedEvents) {
            expect(historyCalls[0][1]).toMatchObject({
                query_kind: NodeKind.HogQLQuery,
                data_warehouse_source_ids: ['src-1'],
                data_warehouse_source_types: ['Postgres'],
            })
        }
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

    it.each([undefined, 'client-query-id'])('emits an event when a query errors with query ID %s', async (queryId) => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const q: EventsQuery = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['error'],
            limit: 100,
        })
        captureSpy.mockClear()
        await expect(async () => {
            await performQuery(q, undefined, undefined, queryId)
        }).rejects.toThrow(ApiError)

        const queryFailedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query failed')
        expect(queryFailedCalls).toHaveLength(1)
        expect(queryFailedCalls[0][1]).toMatchObject({
            query: q,
            queryId,
            duration: expect.any(Number),
            error_status: 500,
            error_code: null,
            submit_request_timings: [
                expect.objectContaining({ request_total_ms: expect.any(Number), http_status: 500 }),
            ],
            time_to_headers_ms: expect.any(Number),
            resource_timing_status: 'missing_request_id',
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

    describe('pollForResults while offline', () => {
        const originalVisibilityState = document.visibilityState

        beforeEach(() => {
            jest.useFakeTimers()
            jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
        })

        afterEach(() => {
            Object.defineProperty(document, 'visibilityState', { value: originalVisibilityState, configurable: true })
            jest.restoreAllMocks()
            jest.useRealTimers()
        })

        it.each(['before polling', 'during the poll delay', 'while hidden'])(
            'waits for reconnect %s without using the deadline',
            async (when) => {
                const online = jest.spyOn(navigator, 'onLine', 'get')
                online.mockReturnValue(when === 'during the poll delay')
                const status = { complete: true, results: ['ok'] }
                const statusSpy = jest.spyOn(api.queryStatus, 'get').mockResolvedValue({ query_status: status } as any)
                const promise = pollForResults('test-query-id')

                if (when === 'during the poll delay') {
                    await jest.advanceTimersByTimeAsync(100)
                    online.mockReturnValue(false)
                }
                await jest.advanceTimersByTimeAsync(11 * 60 * 1000)
                expect(statusSpy).not.toHaveBeenCalled()

                if (when === 'while hidden') {
                    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
                }
                online.mockReturnValue(true)
                window.dispatchEvent(new Event('online'))
                if (when === 'while hidden') {
                    await jest.advanceTimersByTimeAsync(1000)
                    expect(statusSpy).not.toHaveBeenCalled()
                    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
                    document.dispatchEvent(new Event('visibilitychange'))
                }
                await jest.advanceTimersByTimeAsync(300)
                await expect(promise).resolves.toEqual(status)
            }
        )

        it.each([false, true])('recovers an offline poll when already reconnected is %s', async (reconnected) => {
            const online = jest.spyOn(navigator, 'onLine', 'get')
            const querySpy = jest
                .spyOn(api, 'query')
                .mockResolvedValue({ query_status: { id: 'test-query-id', complete: false } } as any)
            const statusSpy = jest
                .spyOn(api.queryStatus, 'get')
                .mockImplementationOnce(async () => {
                    online.mockReturnValue(reconnected)
                    throw new NetworkError('offline')
                })
                .mockResolvedValueOnce({ query_status: { complete: true, results: ['ok'] } } as any)
            const capture = jest.spyOn(posthog, 'capture').mockClear()
            const promise = performQuery({ kind: NodeKind.EventsQuery, select: ['*'] }, undefined, 'async')

            await jest.advanceTimersByTimeAsync(300)
            if (!reconnected) {
                await jest.advanceTimersByTimeAsync(11 * 60 * 1000)
                expect(statusSpy).toHaveBeenCalledTimes(1)
                online.mockReturnValue(true)
                window.dispatchEvent(new Event('online'))
            }
            await jest.advanceTimersByTimeAsync(375)

            await expect(promise).resolves.toEqual(['ok'])
            expect(querySpy).toHaveBeenCalledTimes(1)
            expect(statusSpy.mock.calls.map(([id]) => id)).toEqual(['test-query-id', 'test-query-id'])
            expect(capture.mock.calls.filter(([event]) => event === 'query failed')).toHaveLength(0)
            expect(capture.mock.calls.filter(([event]) => event === 'query completed')).toHaveLength(1)
        })

        it.each(['before polling', 'while waiting'])('cancels offline polling %s', async (when) => {
            jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
            const statusSpy = jest.spyOn(api.queryStatus, 'get')
            const controller = new AbortController()
            if (when === 'before polling') {
                controller.abort()
            }
            const promise = pollForResults('test-query-id', { signal: controller.signal })
            // oxlint-disable-next-line jest/valid-expect -- awaited after the abort below; awaiting here hangs the test
            const rejected = expect(promise).rejects.toMatchObject({ name: 'AbortError' })
            await jest.advanceTimersByTimeAsync(0)
            controller.abort()
            await rejected

            jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
            window.dispatchEvent(new Event('online'))
            await jest.advanceTimersByTimeAsync(1000)
            expect(statusSpy).not.toHaveBeenCalled()
        })
    })

    describe('polling a query the server has forgotten', () => {
        const query = { kind: NodeKind.EventsQuery, select: ['*'] } as EventsQuery
        const submitted = (id: string): any => ({ query_status: { id, complete: false } })
        const forgotten = (): ApiError => new ApiError('Query not found', 404, undefined, { detail: 'Query not found' })

        afterEach(() => {
            jest.restoreAllMocks()
            delete (window as any).POSTHOG_EXPORTED_DATA
        })

        it('runs the query again when its status has expired', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
            const querySpy = jest
                .spyOn(api, 'query')
                .mockResolvedValueOnce(submitted('gone'))
                .mockResolvedValueOnce({ results: ['from the cache'], is_cached: true } as any)
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(forgotten())

            await expect(performQuery(query, undefined, 'async')).resolves.toMatchObject({
                results: ['from the cache'],
            })

            expect(querySpy).toHaveBeenCalledTimes(2)
            // Same ID, so anything holding it still points at the run the user is waiting for.
            expect(querySpy.mock.calls[1][1]?.clientQueryId).toBe('gone')
            expect(captureSpy.mock.calls.find(([event]) => event === 'query completed')?.[1]).toMatchObject({
                client_query_id: 'gone',
                submit_attempts: 2,
                retry_status: 404,
                retry_recovered: true,
            })
        })

        it('reads the cache on the retry rather than forcing the same work twice', async () => {
            const querySpy = jest
                .spyOn(api, 'query')
                .mockResolvedValueOnce(submitted('gone'))
                .mockResolvedValueOnce({ results: ['from the cache'], is_cached: true } as any)
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(forgotten())

            await performQuery(query, undefined, 'force_async')

            // force_async disregards the cache, and the first run already cached what it computed.
            expect(querySpy.mock.calls[0][1]?.refresh).toBe('force_async')
            expect(querySpy.mock.calls[1][1]?.refresh).toBe('async')
        })

        it.each([
            { name: 'a failed rerun', results: undefined, error: true, recovered: false },
            { name: 'an empty result', results: [], error: false, recovered: true },
        ])('records recovery accurately for $name after expiry', async ({ results, error, recovered }) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            jest.spyOn(api, 'query').mockResolvedValueOnce(submitted('gone')).mockResolvedValueOnce(submitted('rerun'))
            jest.spyOn(api.queryStatus, 'get')
                .mockRejectedValueOnce(forgotten())
                .mockResolvedValueOnce({ query_status: { id: 'rerun', complete: true, error, results } } as any)

            await expect(performQuery(query, undefined, 'async')).resolves.toEqual(results)

            expect(capture.mock.calls.find(([event]) => event === 'query completed')?.[1]).toMatchObject({
                submit_attempts: 2,
                retry_status: 404,
                retry_recovered: recovered,
            })
        })

        it.each([
            ['an error that is not a 404', new ApiError('boom', 500), undefined],
            ['a network failure while online', new NetworkError('network'), undefined],
            ['a request during navigation', new NetworkError('navigating'), undefined],
            ['an error with a caller-supplied ID', new ApiError('boom', 500), 'client-query-id'],
            [
                'a warehouse whose connection is down',
                new ApiError('unavailable', 404, undefined, { code: 'managed_warehouse_connection_unavailable' }),
                undefined,
            ],
        ])('reports the failed poll without resubmitting on %s', async (_name, failure, clientQueryId) => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
            const querySpy = jest.spyOn(api, 'query').mockResolvedValueOnce(submitted('gone'))
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(failure)

            await expect(performQuery(query, undefined, 'async', clientQueryId)).rejects.toBe(failure)

            expect(querySpy).toHaveBeenCalledTimes(1)
            const queryFailedCalls = captureSpy.mock.calls.filter((call) => call[0] === 'query failed')
            expect(queryFailedCalls).toHaveLength(1)
            expect(queryFailedCalls[0][1]).toMatchObject({ queryId: 'gone', error_status: failure.status ?? null })
            expect(captureSpy.mock.calls.filter((call) => call[0] === 'query completed')).toHaveLength(0)
        })

        it('gives up when the second attempt is forgotten too', async () => {
            jest.spyOn(api, 'query').mockResolvedValue(submitted('gone'))
            const statusSpy = jest.spyOn(api.queryStatus, 'get').mockRejectedValue(forgotten())

            await expect(performQuery(query, undefined, 'async')).rejects.toMatchObject({ status: 404 })

            expect(statusSpy).toHaveBeenCalledTimes(2)
        })

        it('runs the query again for a tile resuming a recompute, which polls by id but holds the query', async () => {
            const querySpy = jest
                .spyOn(api, 'query')
                .mockResolvedValueOnce({ results: ['from the cache'], is_cached: true } as any)
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(forgotten())

            await expect(
                performQuery(query, undefined, 'async', 'resumed', undefined, undefined, undefined, true)
            ).resolves.toMatchObject({ results: ['from the cache'] })

            expect(querySpy).toHaveBeenCalledTimes(1)
        })

        it('does not even try to resubmit from a shared or exported view', async () => {
            const querySpy = jest.spyOn(api, 'query')
            jest.spyOn(api.queryStatus, 'get').mockRejectedValueOnce(forgotten())
            ;(window as any).POSTHOG_EXPORTED_DATA = { type: 'embed' }

            await expect(
                performQuery(query, undefined, 'async', 'gone', undefined, undefined, undefined, true)
            ).rejects.toMatchObject({ status: 404 })

            expect(querySpy).not.toHaveBeenCalled()
        })
    })

    it('throws a readable ApiError when the query endpoint returns no content', async () => {
        jest.spyOn(api, 'query').mockResolvedValueOnce(null as any)

        const promise = performQuery(
            { kind: NodeKind.EventsQuery, select: ['*'] } as EventsQuery,
            undefined,
            'blocking'
        )
        await expect(promise).rejects.toBeInstanceOf(ApiError)
        await expect(promise).rejects.toMatchObject({ detail: expect.stringContaining('empty response') })
        jest.restoreAllMocks()
    })

    describe('transient query submission failures', () => {
        const query = { kind: NodeKind.EventsQuery, select: ['*'] } as EventsQuery
        const refused = (): ApiError => new ApiError('', 503, undefined, {})
        const badGateway = (): ApiError => new ApiError('', 502, undefined, {})
        const shortCapacityWait = (): ApiError => new ApiError('', 503, new Headers({ 'Retry-After': '5' }), {})

        afterEach(() => {
            jest.useRealTimers()
            jest.restoreAllMocks()
        })

        it.each([
            ['a 502 bad gateway', badGateway, 600, ['ok'], true],
            ['a capacity 503 asked for a short wait', shortCapacityWait, 5000, ['ok'], true],
            [
                'a capacity 503 at the total retry budget',
                () => new ApiError('', 503, new Headers({ 'Retry-After': '20' })),
                20000,
                ['ok'],
                true,
            ],
            ['a capacity retry returns an empty result', shortCapacityWait, 5000, [], true],
            ['a capacity retry returns no result', shortCapacityWait, 5000, null, false],
        ])(
            'submits the same run again once the wait ends after %s, and returns what the retry gets',
            async (_name, makeError, waitMs, results, recovered) => {
                jest.useFakeTimers()
                const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
                const error = makeError()
                const querySpy = jest
                    .spyOn(api, 'query')
                    .mockRejectedValueOnce(error)
                    .mockResolvedValueOnce({ results } as any)

                const promise = performQuery(query, undefined, 'blocking')
                await jest.advanceTimersByTimeAsync(waitMs - 1)
                expect(querySpy).toHaveBeenCalledTimes(1)
                await jest.advanceTimersByTimeAsync(1)

                await expect(promise).resolves.toMatchObject({ results })
                expect(querySpy).toHaveBeenCalledTimes(2)
                const firstId = querySpy.mock.calls[0][1]?.clientQueryId
                expect(firstId).toBeTruthy()
                expect(querySpy.mock.calls[1][1]?.clientQueryId).toBe(firstId)
                const completed = captureSpy.mock.calls.filter(([event]) => event === 'query completed')
                expect(completed).toHaveLength(1)
                expect(completed[0][1]).toMatchObject({
                    client_query_id: firstId,
                    submit_attempts: 2,
                    retry_wait_ms: waitMs,
                    retry_status: error.status,
                    retry_recovered: recovered,
                })
                expect(captureSpy.mock.calls.filter(([event]) => event === 'query failed')).toHaveLength(0)
            }
        )

        it('does not resubmit when the query is aborted during the capacity wait', async () => {
            jest.useFakeTimers()
            const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
            const controller = new AbortController()
            const querySpy = jest
                .spyOn(api, 'query')
                .mockRejectedValueOnce(shortCapacityWait())
                .mockResolvedValueOnce({ results: ['ok'] } as any)

            const outcome = Promise.allSettled([performQuery(query, { signal: controller.signal }, 'blocking')])
            await jest.advanceTimersByTimeAsync(1000)
            expect(querySpy).toHaveBeenCalledTimes(1)

            controller.abort()
            await jest.advanceTimersByTimeAsync(5000)

            await expect(outcome).resolves.toMatchObject([{ status: 'rejected', reason: { name: 'AbortError' } }])
            expect(querySpy).toHaveBeenCalledTimes(1)
            expect(
                captureSpy.mock.calls.filter(([event]) => event === 'query completed' || event === 'query failed')
            ).toHaveLength(0)
        })

        it.each([
            { name: 'empty result', error: false, results: { results: [] }, recovered: true },
            { name: 'error stub', error: true, results: undefined, recovered: false },
            { name: 'errored result', error: true, results: { results: [] }, recovered: false },
        ])('records async recovery only after a usable result ($name)', async ({ error, results, recovered }) => {
            jest.useFakeTimers()
            const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
            jest.spyOn(api, 'query')
                .mockRejectedValueOnce(shortCapacityWait())
                .mockResolvedValueOnce({ query_status: { id: 'retry-query', complete: false } } as any)
            jest.spyOn(api.queryStatus, 'get').mockResolvedValueOnce({
                query_status: { id: 'retry-query', complete: true, error, results },
            } as any)

            const promise = performQuery(query, undefined, 'async', 'retry-query')
            await jest.advanceTimersByTimeAsync(5000)
            expect(captureSpy.mock.calls.filter(([event]) => event === 'query completed')).toHaveLength(0)
            await jest.advanceTimersByTimeAsync(300)
            await expect(promise).resolves.toEqual(results)

            const completed = captureSpy.mock.calls.filter(([event]) => event === 'query completed')
            expect(completed).toHaveLength(1)
            expect(completed[0][1]).toMatchObject({
                client_query_id: 'retry-query',
                submit_attempts: 2,
                retry_wait_ms: 5000,
                retry_status: 503,
                retry_recovered: recovered,
            })
        })

        it.each([
            ['the gateway refuses every attempt', badGateway, 1800, 502],
            ['every attempt gets a short capacity wait', shortCapacityWait, 10000, 503],
            [
                'both capacity waits fit the total budget exactly',
                () => new ApiError('', 503, new Headers({ 'Retry-After': '10' })),
                20000,
                503,
            ],
        ])('reports the failure once %s', async (_name, makeError, elapsedMs, status) => {
            jest.useFakeTimers()
            const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
            const querySpy = jest.spyOn(api, 'query').mockRejectedValue(makeError())

            const outcome = Promise.allSettled([performQuery(query, undefined, 'blocking')])
            await jest.advanceTimersByTimeAsync(elapsedMs - 1)
            expect(querySpy).toHaveBeenCalledTimes(2)
            await jest.advanceTimersByTimeAsync(1)

            await expect(outcome).resolves.toMatchObject([{ status: 'rejected', reason: { status } }])
            expect(querySpy).toHaveBeenCalledTimes(3)
            const failed = captureSpy.mock.calls.filter(([event]) => event === 'query failed')
            expect(failed).toHaveLength(1)
            expect(failed[0][1]).toMatchObject({
                client_query_id: querySpy.mock.calls[0][1]?.clientQueryId,
                submit_attempts: 3,
                retry_wait_ms: elapsedMs,
                retry_status: status,
                error_status: status,
            })
            expect(captureSpy.mock.calls.filter(([event]) => event === 'query completed')).toHaveLength(0)
        })

        it.each([
            ['the two hints exceed the budget', 15, 10, 0],
            ['the failed retry uses the remaining budget', 5, 10, 6000],
        ])('surfaces the full next cooldown when %s', async (_name, firstWait, nextWait, requestTimeMs) => {
            jest.useFakeTimers()
            const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
            let lastError: ApiError | undefined
            const querySpy = jest
                .spyOn(api, 'query')
                .mockRejectedValueOnce(new ApiError('', 503, new Headers({ 'Retry-After': String(firstWait) })))
                .mockImplementationOnce(async () => {
                    await new Promise((resolve) => setTimeout(resolve, requestTimeMs))
                    lastError = new ApiError('', 503, new Headers({ 'Retry-After': String(nextWait) }))
                    throw lastError
                })
                .mockResolvedValue({ results: ['ok'] } as any)

            let receivedError: unknown
            const outcome = performQuery(query, undefined, 'blocking').catch((error) => {
                receivedError = error
            })
            await jest.advanceTimersByTimeAsync(firstWait * 1000 + requestTimeMs + 1)

            expect(receivedError).toBeInstanceOf(ApiError)
            expect(receivedError).toBe(lastError)
            expect(lastError?.retryAfterSeconds).toBe(nextWait)
            await jest.advanceTimersByTimeAsync(60_000)
            await outcome
            expect(querySpy).toHaveBeenCalledTimes(2)
            expect(captureSpy.mock.calls.find(([event]) => event === 'query failed')?.[1]).toMatchObject({
                submit_attempts: 2,
                retry_wait_ms: firstWait * 1000,
                retry_status: 503,
            })
        })

        it.each([
            { waitSeconds: 20, resumedAt: 20_050, retries: true },
            { waitSeconds: 20, resumedAt: 21_000, retries: false },
            { waitSeconds: 5, resumedAt: 21_000, retries: false },
        ])(
            'bounds timer lateness after a $waitSeconds second hint (resumed at $resumedAt ms)',
            async ({ waitSeconds, resumedAt, retries }) => {
                jest.useFakeTimers()
                const captureSpy = jest.spyOn(posthog, 'capture').mockClear()
                const clock = jest.spyOn(performance, 'now').mockReturnValue(0)
                const error = new ApiError('', 503, new Headers({ 'Retry-After': String(waitSeconds) }))
                const querySpy = jest
                    .spyOn(api, 'query')
                    .mockRejectedValueOnce(error)
                    .mockResolvedValue({ results: ['ok'] } as any)

                const outcome = Promise.allSettled([performQuery(query, undefined, 'blocking')])
                await jest.advanceTimersByTimeAsync(0)
                await jest.advanceTimersByTimeAsync(waitSeconds * 1000 - 1)
                expect(querySpy).toHaveBeenCalledTimes(1)
                clock.mockReturnValue(resumedAt)
                await jest.advanceTimersByTimeAsync(1)

                await expect(outcome).resolves.toEqual([
                    retries
                        ? { status: 'fulfilled', value: { results: ['ok'] } }
                        : { status: 'rejected', reason: error },
                ])
                expect(querySpy).toHaveBeenCalledTimes(retries ? 2 : 1)
                const eventName = retries ? 'query completed' : 'query failed'
                expect(captureSpy.mock.calls.find(([event]) => event === eventName)?.[1]).toMatchObject({
                    submit_attempts: retries ? 2 : 1,
                    retry_wait_ms: resumedAt,
                    retry_status: retries ? 503 : null,
                })
            }
        )

        it.each(
            (['force_blocking', 'force_async'] as RefreshType[]).flatMap((refresh) =>
                [502, 503].map((status) => ({ refresh, status }))
            )
        )(
            'retries $refresh only with a capacity hint, not an ambiguous gateway failure (status=$status)',
            async ({ refresh, status }) => {
                jest.useFakeTimers()
                const error = status === 502 ? badGateway() : shortCapacityWait()
                const querySpy = jest
                    .spyOn(api, 'query')
                    .mockRejectedValueOnce(error)
                    .mockResolvedValue({ results: ['ok'] } as any)

                const outcome = Promise.allSettled([performQuery(query, undefined, refresh)])
                await jest.advanceTimersByTimeAsync(4999)
                expect(querySpy).toHaveBeenCalledTimes(1)
                await jest.advanceTimersByTimeAsync(1)

                await expect(outcome).resolves.toEqual([
                    status === 502
                        ? { status: 'rejected', reason: error }
                        : { status: 'fulfilled', value: { results: ['ok'] } },
                ])
                expect(querySpy).toHaveBeenCalledTimes(status === 502 ? 1 : 2)
            }
        )

        it.each([
            ['a 503 without Retry-After', refused()],
            ['a 503 above the total retry budget', new ApiError('', 503, new Headers({ 'Retry-After': '21' }), {})],
            ['a 503 with an invalid Retry-After', new ApiError('', 503, new Headers({ 'Retry-After': '1.5' }), {})],
            [
                'a 503 with a date-form Retry-After',
                new ApiError('', 503, new Headers({ 'Retry-After': 'Mon, 05 Oct 2026 12:00:05 GMT' }), {}),
            ],
            ['a capacity 503 with Retry-After', new ApiError('', 503, new Headers({ 'Retry-After': '45' }), {})],
            ['a 504, where the backend can still be running the query', new ApiError('', 504, undefined, {})],
        ])('does not submit again after %s', async (_name, error) => {
            jest.useFakeTimers()
            const querySpy = jest.spyOn(api, 'query').mockRejectedValue(error)

            const outcome = Promise.allSettled([performQuery(query, undefined, 'blocking')])
            await jest.advanceTimersByTimeAsync(60_000)

            await expect(outcome).resolves.toEqual([{ status: 'rejected', reason: error }])
            expect(querySpy).toHaveBeenCalledTimes(1)
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
