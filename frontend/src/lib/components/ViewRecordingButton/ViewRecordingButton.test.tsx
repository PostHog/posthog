import { recordingDisabledReason } from './ViewRecordingButton'

describe('recordingDisabledReason', () => {
    // Malformed SDK payloads can send $session_id as a non-string (dict/array/number). Such a value
    // can't address a recording; without this guard the button stays enabled and links to
    // /replay/[object Object]. See the events-query non-string $session_id fix.
    it.each([
        ['object', { bytes: { 0: 1 } }],
        ['array', [1, 2, 3]],
        ['number', 12345],
    ])('disables with "No recording for this event" when $session_id is a %s', (_label, sessionId) => {
        expect(recordingDisabledReason(sessionId as unknown as string, undefined, undefined)).toBe(
            'No recording for this event'
        )
    })

    it('does not disable for a valid string session id with a recording', () => {
        expect(recordingDisabledReason('0190-good-session', undefined, true)).toBeNull()
    })

    it('disables when the server reports no recording exists', () => {
        expect(recordingDisabledReason('0190-good-session', undefined, false)).toBe('No recording for this event')
    })

    it('prompts to set a session id when it is genuinely absent', () => {
        // Absent (not malformed) keeps the existing "no session id" guidance rather than "no recording".
        expect(recordingDisabledReason(undefined, undefined, undefined)).not.toBeNull()
        expect(typeof recordingDisabledReason(undefined, undefined, undefined)).not.toBe('string')
    })

    it.each([['disabled'], ['missing_config']])('disables and explains replay was off for the %s status', (status) => {
        expect(recordingDisabledReason('0190-good-session', status, undefined)).not.toBeNull()
    })

    it.each([['disabled'], ['missing_config']])(
        'does not block the %s status once a recording is known to exist',
        (status) => {
            // $recording_status is per page load; a confirmed session recording must still be viewable.
            expect(recordingDisabledReason('0190-good-session', status, true)).toBeNull()
        }
    )

    it.each([['lazy_loading'], ['awaiting_config'], ['paused'], ['some_future_status']])(
        'does not claim replay was off for the transient %s status',
        (status) => {
            expect(recordingDisabledReason('0190-good-session', status, undefined)).toBeNull()
        }
    )
})
