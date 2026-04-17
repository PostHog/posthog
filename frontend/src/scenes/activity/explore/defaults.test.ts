import { NodeKind } from '~/queries/schema/schema-general'

import { getDefaultEventsSceneQuery, getDefaultSessionsSceneQuery } from './defaults'

describe('activity explore defaults', () => {
    // High-volume teams OOM on larger default windows because SESSION_BUFFER_DAYS
    // further expands the raw_sessions scan server-side. Guard against accidental widening.
    it('defaults the sessions scene query to the last 1 hour', () => {
        const query = getDefaultSessionsSceneQuery()
        expect(query.source.kind).toBe(NodeKind.SessionsQuery)
        expect(query.source).toMatchObject({ after: '-1h' })
    })

    it('defaults the events scene query to the last 1 hour', () => {
        const query = getDefaultEventsSceneQuery()
        expect(query.source.kind).toBe(NodeKind.EventsQuery)
        expect(query.source).toMatchObject({ after: '-1h' })
    })
})
