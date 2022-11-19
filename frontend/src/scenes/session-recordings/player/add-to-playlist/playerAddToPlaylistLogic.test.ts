import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { expectLogic } from 'kea-test-utils'
import { playerAddToPlaylistLogic } from 'scenes/session-recordings/player/add-to-playlist/playerAddToPlaylistLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'

describe('playerAddToPlaylistLogic', () => {
    let logic: ReturnType<typeof playerAddToPlaylistLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recording_playlists/:id': [200, 'retrieved playlist'],
                '/api/projects/:team/session_recording_playlists': {
                    results: 'list of retrieved playlists',
                    count: 42,
                    filters: null,
                },
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

    describe('playlist logic', () => {
        beforeEach(() => {
            logic = playerAddToPlaylistLogic()
            logic.mount()
        })

        describe('core assumptions', () => {
            it('mounts a bunch of other logics', async () => {
                await expectLogic(logic).toMount([savedSessionRecordingPlaylistModelLogic, sessionRecordingDataLogic])
            })

            it('loads playlists after mounting', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadPlaylists', 'loadPlaylistsSuccess'])
                    .toMatchValues({
                        playlistsResponse: {
                            results: 'list of retrieved playlists',
                            count: 42,
                            filters: null,
                        },
                    })
            })
        })
    })

    describe('actions', () => {
        beforeEach(() => {
            logic = playerAddToPlaylistLogic()
            logic.mount()
        })

        it('addNewPlaylist', async () => {})
        it('setSearchQuery', () => {})
        it('setRecording', () => {})
        it('setScrollIndex', () => {})
        it('addToPlaylist sets parent level metadata playlists', () => {})
        it('removeFromPlaylist sets parent level metadata playlists', () => {})
    })
})
