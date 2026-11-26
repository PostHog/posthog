import { NodeKind } from '~/queries/schema/schema-general'

import { getDefaultEventsSceneQuery, getDefaultSessionsSceneQuery, widerActivityRange } from './defaults'

describe('activity explore defaults', () => {
    test.each([
        ['sessions', getDefaultSessionsSceneQuery, NodeKind.SessionsQuery],
        ['events', getDefaultEventsSceneQuery, NodeKind.EventsQuery],
    ] as const)('defaults the %s scene query to the last 1 hour', (_, getQuery, kind) => {
        const query = getQuery()
        expect(query.source.kind).toBe(kind)
        expect(query.source).toMatchObject({ after: '-1h' })
    })

    describe('widerActivityRange', () => {
        test.each([
            ['-1h', '-24h', 'Show last 24 hours'],
            ['-24h', '-7d', 'Show last 7 days'],
            ['-7d', '-30d', 'Show last 30 days'],
        ])('steps %s up to %s', (after, widerAfter, label) => {
            expect(widerActivityRange(after, undefined)).toEqual({ after: widerAfter, label })
        })

        test.each([
            ['a custom range', '-3h', undefined],
            ['the widest step', '-30d', undefined],
            ['a missing after', undefined, undefined],
            ['a bounded range', '-1h', '-30m'],
        ])('returns null for %s', (_, after, before) => {
            expect(widerActivityRange(after, before)).toBeNull()
        })
    })
})
