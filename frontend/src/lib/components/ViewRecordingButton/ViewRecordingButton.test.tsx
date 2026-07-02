import { recordingDisabledReason } from './ViewRecordingButton'

describe('recordingDisabledReason', () => {
    it('disables when replay is opted out, even for an otherwise-playable recording', () => {
        // Guards the persons-modal dead-click bug: sessionId present + hasRecording true used to
        // return null (clickable) despite the project having session_recording_opt_in = false.
        const reason = recordingDisabledReason('a-session-id', undefined, true, false)
        expect(reason).not.toBeNull()
    })

    it.each([
        ['opt-in true, playable recording', 'a-session-id', undefined, true, true, null],
        ['opt-in unknown, playable recording', 'a-session-id', undefined, true, undefined, null],
        ['missing session id', undefined, undefined, undefined, true, 'not-null'],
        ['no recording for event', 'a-session-id', undefined, false, true, 'not-null'],
    ] as const)('%s', (_name, sessionId, recordingStatus, hasRecording, optIn, expected) => {
        const reason = recordingDisabledReason(sessionId, recordingStatus, hasRecording, optIn)
        if (expected === null) {
            expect(reason).toBeNull()
        } else {
            expect(reason).not.toBeNull()
        }
    })
})
