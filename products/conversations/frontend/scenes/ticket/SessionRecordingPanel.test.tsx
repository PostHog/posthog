import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { recordingIdFromReplayUrl, SessionRecordingPanel } from './SessionRecordingPanel'

jest.mock('scenes/session-recordings/player/SessionRecordingPlayer', () => ({
    SessionRecordingPlayer: ({ sessionRecordingId }: { sessionRecordingId: string }) => (
        <div data-attr="session-recording-player">{sessionRecordingId}</div>
    ),
}))

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

// These exercise the component's `sessionContext?.replay_url` wiring, not just the helper, so a
// revert to the old `session_replay_url` key would fail here even though the helper still works.
describe('SessionRecordingPanel', () => {
    afterEach(() => {
        cleanup()
    })

    it('passes the id parsed from sessionContext.replay_url to the player', async () => {
        render(<SessionRecordingPanel sessionContext={{ replay_url: 'https://us.posthog.com/replay/01890abc' }} />)

        await userEvent.click(screen.getByText('Session recording'))

        expect(screen.getByText('01890abc')).toBeInTheDocument()
    })

    it('shows the empty state when sessionContext has no replay_url', async () => {
        render(<SessionRecordingPanel sessionContext={{}} />)

        await userEvent.click(screen.getByText('Session recording'))

        expect(screen.getByText('No session recording available')).toBeInTheDocument()
    })
})
