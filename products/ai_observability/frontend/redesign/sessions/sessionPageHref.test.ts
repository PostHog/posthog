import { sessionPageHref } from './sessionPageHref'

describe('sessionPageHref', () => {
    test.each<[string, string, string | null, string | null]>([
        ['a plain id', 'session-1', null, '/ai-observability/sessions/session-1?date_from=-7d'],
        [
            'an id with its start',
            'session-1',
            '2026-08-01T10:00:00Z',
            '/ai-observability/sessions/session-1?timestamp=2026-08-01T10%3A00%3A00Z&date_from=-7d',
        ],
        ['an id with dots in it', 'v1.2..3', null, '/ai-observability/sessions/v1.2..3?date_from=-7d'],
        [
            'an id of 400 characters',
            'a'.repeat(400),
            null,
            `/ai-observability/sessions/${'a'.repeat(400)}?date_from=-7d`,
        ],
        ['a single dot', '.', null, null],
        ['two dots', '..', null, null],
        ['an id of 401 characters', 'a'.repeat(401), null, null],
    ])('links %s', (_name, sessionId, timestamp, href) => {
        expect(sessionPageHref(sessionId, timestamp, { date_from: '-7d' })).toEqual(href)
    })
})
