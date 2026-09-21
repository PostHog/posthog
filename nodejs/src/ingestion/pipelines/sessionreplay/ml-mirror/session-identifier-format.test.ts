import { mlSessionIdDropReason } from './session-identifier-format'

describe('mlSessionIdDropReason', () => {
    const startedAt = Date.UTC(2026, 8, 15, 12)
    const sessionId = '01a0a4f0-3200-7000-8000-000000000001'
    const day = 24 * 60 * 60 * 1000

    it.each([
        ['at the age limit', startedAt + 14 * day, null],
        ['past the age limit', startedAt + 14 * day + 1, 'session_id_too_old'],
        ['at the future limit', startedAt - day, null],
        ['past the future limit', startedAt - day - 1, 'session_id_in_future'],
    ])('%s', (_, nowMs, reason) => {
        expect(mlSessionIdDropReason(sessionId, nowMs)).toBe(reason)
    })

    it('rejects a session ID that is not a UUIDv7 before checking its age', () => {
        expect(mlSessionIdDropReason('not-a-session', startedAt)).toBe('session_id_not_uuid_v7')
        expect(mlSessionIdDropReason('6ba7b810-9dad-41d1-80b4-00c04fd430c8', startedAt)).toBe('session_id_not_uuid_v7')
    })
})
