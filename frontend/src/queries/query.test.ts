import { queryExportContext } from '~/queries/query'
import { EventsQuery, NodeKind } from '~/queries/schema'
import { PropertyFilterType, PropertyOperator } from '~/types'
import { initKeaTests } from '~/test/init'
import { MOCK_TEAM_ID } from 'lib/api.mock'

describe('query', () => {
    beforeEach(() => {
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
            body: {
                after: expect.any(String),
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
            method: 'POST',
            path: `/api/projects/${MOCK_TEAM_ID}/query`,
        })
    })
})
