import { recordingIdFromReplayUrl } from './SessionRecordingPanel'

describe('recordingIdFromReplayUrl', () => {
    it.each([
        ['https://us.posthog.com/replay/01890abc', '01890abc'],
        ['https://us.posthog.com/replay/01890abc?t=12', '01890abc'],
        ['https://us.posthog.com/replay/01890abc/', '01890abc'],
        ['/replay/01890abc', '01890abc'],
    ])('reads the recording id out of %s', (replayUrl, expected) => {
        expect(recordingIdFromReplayUrl(replayUrl)).toEqual(expected)
    })

    it.each([[undefined], ['']])('returns null for %s', (replayUrl) => {
        expect(recordingIdFromReplayUrl(replayUrl)).toBeNull()
    })
})
