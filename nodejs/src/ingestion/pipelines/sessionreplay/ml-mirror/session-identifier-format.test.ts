import { mlSessionIdDropReason, usesV3Dataset } from './session-identifier-format'

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

describe('usesV3Dataset', () => {
    it.each([
        ['just before 18:00 Europe/London on 2026-09-21', '2026-09-21T16:59:59.999Z', false],
        ['at 18:00 Europe/London on 2026-09-21', '2026-09-21T17:00:00Z', true],
    ])('%s', (_, date, v3) => {
        const hex = Date.parse(date).toString(16).padStart(12, '0')
        expect(usesV3Dataset(`${hex.slice(0, 8)}-${hex.slice(8)}-7000-8000-000000000001`)).toBe(v3)
    })
})
