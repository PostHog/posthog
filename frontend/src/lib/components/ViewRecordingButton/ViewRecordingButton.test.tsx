import { recordingDisabledReason, recordingWarningReason } from './ViewRecordingButton'

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

    // The SDK reports how far the recorder got, not whether a recording exists. Blocking on a status
    // that only means "not started yet" hid recordings that were captured moments later.
    it.each([
        ['active', false],
        ['sampled', false],
        ['buffering', false],
        ['lazy_loading', false],
        ['awaiting_config', false],
        ['pending_config', false],
        ['paused', false],
        ['a_status_this_build_does_not_know', false],
        // Event properties carry any key a client sends, including names inherited from Object.prototype.
        ['toString', false],
        ['__proto__', false],
        ['disabled', true],
        ['missing_config', true],
        ['rrweb_error', true],
    ])('%s status blocks the button: %s', (recordingStatus, blocks) => {
        expect(recordingDisabledReason('0190-good-session', recordingStatus, undefined) !== null).toBe(blocks)
    })

    it.each(['disabled', 'missing_config', 'rrweb_error', 'lazy_loading'])(
        'never blocks a known recording, whatever %s claims',
        (recordingStatus) => {
            expect(recordingDisabledReason('0190-good-session', recordingStatus, true)).toBeNull()
        }
    )
})

describe('recordingWarningReason', () => {
    // Transient statuses no longer block, so the warning is the only caveat the user gets.
    it.each(['buffering', 'lazy_loading', 'awaiting_config', 'pending_config', 'paused'])(
        'warns that a recording may be missing for %s',
        (recordingStatus) => {
            expect(recordingWarningReason(undefined, undefined, recordingStatus, undefined)).toContain(
                'There may not be a recording to watch'
            )
        }
    )

    it.each(['active', 'sampled', 'disabled', 'toString', '__proto__'])('does not warn for %s', (recordingStatus) => {
        expect(recordingWarningReason(undefined, undefined, recordingStatus, undefined)).toBeUndefined()
    })
})
