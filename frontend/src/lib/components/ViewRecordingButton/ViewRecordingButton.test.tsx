import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { recordingDisabledReason } from './ViewRecordingButton'

describe('recordingDisabledReason', () => {
    afterEach(cleanup)

    // The funnel drop-off persons modal renders a disabled button for actors with no matched recording
    // (sessionId undefined, hasRecording false). The old copy ("No recording for this event") read as
    // replay being off project-wide, generating support tickets. It must instead explain the per-user
    // cause and offer the Session replay fallback link when one is supplied.
    it('explains the per-user cause and links to the person fallback when no recording exists', () => {
        const reason = recordingDisabledReason(undefined, undefined, false, '/person/abc#activeTab=sessionRecordings')
        render(<>{reason}</>)

        expect(screen.queryByText('No recording for this event')).not.toBeInTheDocument()
        expect(screen.getByText(/session ID/)).toBeInTheDocument()
        const fallbackLink = screen.getByText("browse this person's sessions")
        expect(fallbackLink.closest('a')).toHaveAttribute('href', '/person/abc#activeTab=sessionRecordings')
    })

    it('omits the fallback link when no fallback URL is supplied', () => {
        const reason = recordingDisabledReason(undefined, undefined, false)
        render(<>{reason}</>)

        expect(screen.queryByText("browse this person's sessions")).not.toBeInTheDocument()
    })

    it('returns no reason when a recording is available', () => {
        expect(recordingDisabledReason('session-1', 'active', true)).toBeNull()
    })
})
