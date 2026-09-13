import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getDefaultEventsSceneQuery, getDefaultSessionsSceneQuery, getPersonEventsSceneQuery } from './defaults'

describe('activity explore defaults', () => {
    test.each([
        ['sessions', getDefaultSessionsSceneQuery, NodeKind.SessionsQuery],
        ['events', getDefaultEventsSceneQuery, NodeKind.EventsQuery],
    ] as const)('defaults the %s scene query to the last 1 hour', (_, getQuery, kind) => {
        const query = getQuery()
        expect(query.source.kind).toBe(kind)
        expect(query.source).toMatchObject({ after: '-1h' })
    })

    it('centers a person events query on the event it was opened from', () => {
        const source = getPersonEventsSceneQuery('the-distinct-id', '2026-09-07T09:00:00Z').source as EventsQuery

        expect(source).toMatchObject({ after: '2026-09-07T08:00:00.000Z', before: '2026-09-07T10:00:00.000Z' })
        expect(source.properties).toEqual([
            {
                type: PropertyFilterType.EventMetadata,
                key: 'distinct_id',
                value: 'the-distinct-id',
                operator: PropertyOperator.Exact,
            },
        ])
    })

    test.each([
        ['no anchor', undefined],
        ['an unparseable anchor', 'yesterday-ish'],
    ])('widens a person events query past the scene default given %s', (_, anchor) => {
        const source = getPersonEventsSceneQuery('the-distinct-id', anchor).source as EventsQuery

        expect(source.after).toBe('-7d')
        expect(source.before).toBeUndefined()
    })
})
