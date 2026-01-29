import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { performQuery, pollForResults, queryExportContext } from '~/queries/query'
import { EventsQuery, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { setLatestVersionsOnQuery } from './utils'

describe('query', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query': (req) => {
                    const data = req.body as any
                    if (data.query?.kind === 'HogQLQuery') {
                        return [
                            200,
                            { results: [], clickhouse: 'clickhouse string', hogql: 'hogql string', is_cached: false },
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
        expect(queryFailedCalls[0][1]).toMatchObject({ query: q, duration: expect.any(Number) })
    })

    describe('pollForResults error message parsing', () => {
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
