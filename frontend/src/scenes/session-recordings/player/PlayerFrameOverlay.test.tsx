import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { PlayerFrameOverlay } from 'scenes/session-recordings/player/PlayerFrameOverlay'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { setupSessionRecordingTest } from './__mocks__/test-setup'

describe('PlayerFrameOverlay', () => {
    let logic: ReturnType<typeof sessionRecordingPlayerLogic.build>
    const logicProps = { sessionRecordingId: '2', playerKey: 'test', blobV2PollingDisabled: true }

    beforeEach(() => {
        // Every snapshot fetch fails, so a retry in these tests behaves like the failure the overlay
        // is showing, instead of silently succeeding against the default mocks.
        setupSessionRecordingTest({
            getMocks: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                '/api/projects/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
            },
        })
        logic = sessionRecordingPlayerLogic(logicProps)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    const renderOverlay = (): void => {
        render(
            <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                <PlayerFrameOverlay />
            </BindLogic>
        )
    }

    // Retrying a terminal snapshot response can never work, so the button must not be offered.
    it.each(['snapshotUnauthorized', 'snapshotForbidden', 'recordingNotFound', 'recordingDeleted'])(
        'offers no retry for %s',
        (playerError) => {
            logic.actions.setPlayerError(playerError)
            renderOverlay()

            expect(screen.queryByText('Retry')).toBeNull()
        }
    )

    it('offers a retry for a failure a fresh attempt can fix', () => {
        logic.actions.setPlayerError('loadSnapshotsForSourceFailure')
        renderOverlay()

        expect(screen.queryByText('Retry')).not.toBeNull()
    })

    it('stops offering a retry once the person has retried twice', () => {
        logic.actions.setPlayerError('loadSnapshotsForSourceFailure')
        logic.actions.retryLoadingSnapshots()
        logic.actions.setPlayerError('loadSnapshotsForSourceFailure')
        logic.actions.retryLoadingSnapshots()
        logic.actions.setPlayerError('loadSnapshotsForSourceFailure')
        renderOverlay()

        expect(screen.queryByText('Retry')).toBeNull()
        expect(screen.queryByText(/Retrying hasn't helped/)).not.toBeNull()
    })
})
