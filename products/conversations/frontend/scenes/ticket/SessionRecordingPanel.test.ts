import { recordingIdFromReplayUrl } from './SessionRecordingPanel'

describe('recordingIdFromReplayUrl', () => {
    it.each([
        ['/replay/abc123', 'abc123'],
        ['/replay/abc123?t=42', 'abc123'],
        ['https://us.posthog.com/replay/abc123?source=widget', 'abc123'],
        [undefined, null],
        ['', null],
    ])('parses %p to %p', (input, expected) => {
        expect(recordingIdFromReplayUrl(input)).toBe(expected)
    })

    // session_context comes from the public widget endpoint, which stores non-string scalars verbatim.
    // A non-string value must resolve to no recording instead of crashing the ticket scene.
    it.each([42, true, { url: '/replay/abc123' }, ['/replay/abc123'], null])(
        'returns null for the non-string value %p',
        (input) => {
            expect(recordingIdFromReplayUrl(input)).toBeNull()
        }
    )
})
