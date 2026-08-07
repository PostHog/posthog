import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import {
    performQuery,
    pollForResults,
    queryExportContext,
    stripRetiredQueryFields,
    waitForPageVisible,
} from '~/queries/query'
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

    describe('stripRetiredQueryFields', () => {
        it('drops retired keys from nested modifiers without touching the rest of the query', () => {
            const cleaned = stripRetiredQueryFields({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['timestamp'],
                    modifiers: {
                        usePresortedEventsTable: true,
                        personsOnEventsMode: 'person_id_override_properties_joined',
                    },
                },
            })

            expect(cleaned).toEqual({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['timestamp'],
                    modifiers: { personsOnEventsMode: 'person_id_override_properties_joined' },
                },
            })
        })

        it('leaves free-form HogQL variable values untouched', () => {
            const query = {
                kind: NodeKind.HogQLQuery,
                query: 'select 1',
                values: { usePresortedEventsTable: 'a user-supplied value we must not drop' },
            }
            expect(stripRetiredQueryFields(query)).toEqual(query)
        })

        it('returns the same reference and terminates on a self-referential query', () => {
            // performQuery runs this on every query; a cyclic object must not hang the recursion.
            const query: Record<string, any> = { kind: NodeKind.HogQLQuery, query: 'select 1' }
            query.self = query
            const result = stripRetiredQueryFields(query)
            expect(result).toBe(query)
        })
    })

    it('strips retired query fields before sending the request to the backend', async () => {
        let sentBody: any
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    sentBody = await request.json()
                    return [200, { results: [], is_cached: false }]
                },
            },
        })
        const q = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['timestamp'],
            modifiers: { usePresortedEventsTable: true },
        }) as EventsQuery
        await performQuery(q)
        expect(sentBody.query.modifiers).not.toHaveProperty('usePresortedEventsTable')
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
