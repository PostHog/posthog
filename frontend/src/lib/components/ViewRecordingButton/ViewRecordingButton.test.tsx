import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { recordingDisabledReason } from './ViewRecordingButton'

describe('recordingDisabledReason', () => {
    afterEach(() => {
        cleanup()
    })

    it('returns the actionable "No session ID" guidance when sessionId is missing and hasRecording is false', () => {
        const result = recordingDisabledReason(undefined, undefined, false)
        const { getByText, getByRole } = render(<>{result}</>)

        expect(getByText(/No session ID associated with this event/)).toBeInTheDocument()
        const link = getByRole('link', { name: /Learn how/i })
        expect(link).toHaveAttribute('href', 'https://posthog.com/docs/data/sessions#automatically-sending-session-ids')
    })

    it('returns the "No session ID" guidance when sessionId is missing and hasRecording is undefined', () => {
        const result = recordingDisabledReason(undefined, undefined, undefined)
        const { getByText } = render(<>{result}</>)

        expect(getByText(/No session ID associated with this event/)).toBeInTheDocument()
    })

    it('returns "No recording for this event" when sessionId is set but hasRecording is false', () => {
        const result = recordingDisabledReason('session-abc', undefined, false)
        expect(result).toBe('No recording for this event')
    })

    it('returns the inactive-replay message when recordingStatus indicates replay was not active', () => {
        const result = recordingDisabledReason('session-abc', 'disabled', true)
        const { getByText } = render(<>{result}</>)

        expect(getByText(/Replay was not active when capturing this event/)).toBeInTheDocument()
    })

    it('returns null when sessionId is set, recording exists, and replay was active', () => {
        expect(recordingDisabledReason('session-abc', 'active', true)).toBeNull()
    })

    it('returns null when sessionId is set and hasRecording / recordingStatus are undefined', () => {
        expect(recordingDisabledReason('session-abc', undefined, undefined)).toBeNull()
    })
})
