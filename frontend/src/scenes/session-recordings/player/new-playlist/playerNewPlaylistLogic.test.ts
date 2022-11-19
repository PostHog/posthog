import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import { expectLogic } from 'kea-test-utils'
import { playerNewPlaylistLogic } from 'scenes/session-recordings/player/new-playlist/playerNewPlaylistLogic'

describe('playerNewPlaylistLogic', () => {
    let logic: ReturnType<typeof playerNewPlaylistLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists/:id': [200, 'retrieved playlist'],
            },
            post: {
                '/api/projects/:team/session_recording_playlists': [200, 'created playlists'],
            },
            patch: {
                '/api/projects/:team/session_recording_playlists/:id': [200, 'updated playlist'],
                '/api/projects/:team/session_recordings/:id': [
                    200,
                    {
                        result: {
                            session_recording: 'updated recording',
                        },
                    },
                ],
            },
        })
        initKeaTests()
    })

    describe('core assumptions', () => {
        beforeEach(() => {
            logic = playerNewPlaylistLogic()
            logic.mount()
        })

        it('mounts a bunch of other logics', async () => {
            await expectLogic(logic).toMount([savedSessionRecordingPlaylistModelLogic])
        })
    })

    describe('creating playlists', () => {
        beforeEach(() => {
            logic = playerNewPlaylistLogic()
            logic.mount()
        })
        it('createPlaylist', async () => {})
        it('createAndGoToPlaylist', () => {})
    })
})
