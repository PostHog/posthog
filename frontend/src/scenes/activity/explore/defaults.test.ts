import { NodeKind } from '~/queries/schema/schema-general'

import {
    PERSON_EVENTS_LINK_DATE_RANGE,
    getDefaultEventsSceneQuery,
    getDefaultSessionsSceneQuery,
    getPersonEventsLinkDateRange,
} from './defaults'

describe('activity explore defaults', () => {
    test.each([
        ['sessions', getDefaultSessionsSceneQuery, NodeKind.SessionsQuery],
        ['events', getDefaultEventsSceneQuery, NodeKind.EventsQuery],
    ] as const)('defaults the %s scene query to the last 1 hour', (_, getQuery, kind) => {
        const query = getQuery()
        expect(query.source.kind).toBe(kind)
        expect(query.source).toMatchObject({ after: '-1h' })
    })

    test('carries both bounds of an explicit date range into the events scene query', () => {
        const query = getDefaultEventsSceneQuery(undefined, { after: '-1dStart', before: '-1dEnd' })
        expect(query.source).toMatchObject({ after: '-1dStart', before: '-1dEnd' })
    })

    test.each([
        [
            'an events query in the hash',
            { q: { source: { kind: NodeKind.EventsQuery, after: '-1dStart', before: '-1dEnd' } } },
            { after: '-1dStart', before: '-1dEnd' },
        ],
        [
            'an open-ended events query',
            { q: { source: { kind: NodeKind.EventsQuery, after: '-30d' } } },
            { after: '-30d', before: undefined },
        ],
        ['no query in the hash', {}, PERSON_EVENTS_LINK_DATE_RANGE],
        [
            'a query of another kind',
            { q: { source: { kind: NodeKind.HogQLQuery, after: '-1h' } } },
            PERSON_EVENTS_LINK_DATE_RANGE,
        ],
    ])('resolves the person link date range from %s', (_, hashParams, expected) => {
        expect(getPersonEventsLinkDateRange(hashParams)).toEqual(expected)
    })
})
