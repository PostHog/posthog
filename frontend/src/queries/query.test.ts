import { query, queryExportContext } from '~/queries/query'
import { EventsQuery, HogQLQuery, NodeKind } from '~/queries/schema'
import { PropertyFilterType, PropertyOperator } from '~/types'
import { initKeaTests } from '~/test/init'
import posthog from 'posthog-js'
import { useMocks } from '~/mocks/jest'

describe('query', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:team/query': (req) => {
                    const data = req.body as any
                    if (data.query?.kind === 'HogQLQuery') {
                        return [200, { results: [], clickhouse: 'clickhouse string', hogql: 'hogql string' }]
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
        jest.spyOn(posthog, 'capture')
        const q: EventsQuery = {
            kind: NodeKind.EventsQuery,
            select: ['timestamp'],
            limit: 100,
        }
        await query(q)
        expect(posthog.capture).toHaveBeenCalledWith('query completed', { query: q, duration: expect.any(Number) })
    })

    it('emits a specific event on a HogQLQuery', async () => {
        jest.spyOn(posthog, 'capture')
        const q: HogQLQuery = {
            kind: NodeKind.HogQLQuery,
            query: 'select * from events',
        }
        await query(q)
        expect(posthog.capture).toHaveBeenCalledWith('query completed', {
            query: q,
            duration: expect.any(Number),
            clickhouse_sql: expect.any(String),
        })
    })

    it('emits an event when a query errors', async () => {
        jest.spyOn(posthog, 'capture')
        const q: EventsQuery = {
            kind: NodeKind.EventsQuery,
            select: ['error'],
            limit: 100,
        }
        await expect(async () => {
            await query(q)
        }).rejects.toStrictEqual({
            status: 500,
            detail: 'error',
        })

        expect(posthog.capture).toHaveBeenCalledWith('query failed', { query: q, duration: expect.any(Number) })
    })
})
