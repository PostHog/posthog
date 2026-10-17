import { NodeKind } from '~/queries/schema/schema-general'

import { getDefaultEventsSceneQuery, getDefaultSessionsSceneQuery, getDistinctIdEventsSceneQuery } from './defaults'

describe('activity explore defaults', () => {
    test.each([
        ['sessions', getDefaultSessionsSceneQuery, NodeKind.SessionsQuery],
        ['events', getDefaultEventsSceneQuery, NodeKind.EventsQuery],
    ] as const)('defaults the %s scene query to the last 1 hour', (_, getQuery, kind) => {
        const query = getQuery()
        expect(query.source.kind).toBe(kind)
        expect(query.source).toMatchObject({ after: '-1h' })
    })

    it('looks back 7 days for events of one distinct ID', () => {
        expect(getDistinctIdEventsSceneQuery('the-distinct-id').source).toMatchObject({
            after: '-7d',
            properties: [{ key: 'distinct_id', value: 'the-distinct-id' }],
        })
    })
})
