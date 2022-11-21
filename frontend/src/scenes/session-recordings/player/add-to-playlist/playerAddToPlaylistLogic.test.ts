import { initKeaTests } from '~/test/init'
import { useMocks } from '~/mocks/jest'
import { expectLogic } from 'kea-test-utils'
import { playerAddToPlaylistLogic } from 'scenes/session-recordings/player/add-to-playlist/playerAddToPlaylistLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'

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
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
            post: {
                '/api/projects/:team/session_recording_playlists': [200, 'created playlists'],
            },
            patch: {
                '/api/projects/:team/session_recording_playlists/:id': [200, 'updated playlist'],
                '/api/projects/:team/session_recordings/:id': {
                    result: {
                        session_recording: {
                            playlists: ['updated playlist'],
                        },
                    },
                },
            },
        })
        initKeaTests()
    })

    describe('playlist logic', () => {
        beforeEach(() => {
            logic = playerAddToPlaylistLogic({
                sessionRecordingId: '1',
                playerKey: 'test',
            })
            logic.mount()
        })

        describe('core assumptions', () => {
            it('mounts a bunch of other logics', async () => {
                await expectLogic(logic).toMount([
                    savedSessionRecordingPlaylistModelLogic,
                    sessionRecordingDataLogic({
                        sessionRecordingId: '1',
                        playerKey: 'test',
                    }),
                ])
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
            logic = playerAddToPlaylistLogic({
                sessionRecordingId: 'nightly',
                playerKey: 'test',
            })
            logic.mount()
        })

        it('addToPlaylist sets parent level metadata playlists', async () => {
            await expectLogic(logic, async () => {
                logic.actions.addToPlaylist({
                    short_id: 'abc',
                    id: 1,
                })
            })
                .toDispatchActions([
                    'addToPlaylist',
                    'addRecordingToPlaylist',
                    'addRecordingToPlaylistSuccess',
                    'setRecordingMeta',
                    sessionRecordingDataLogic({
                        sessionRecordingId: 'nightly',
                        playerKey: 'test',
                    }).actionTypes.setRecordingMetaSuccess,
                ])
                .toMatchValues({
                    sessionPlayerMetaData: expect.objectContaining({
                        metadata: expect.objectContaining({
                            playlists: ['updated playlist'],
                        }),
                    }),
                })
        })
        it('removeFromPlaylist sets parent level metadata playlists', async () => {
            await expectLogic(logic, async () => {
                logic.actions.removeFromPlaylist({
                    short_id: 'abc',
                    id: 1,
                })
            })
                .toDispatchActions([
                    'removeFromPlaylist',
                    'removeRecordingFromPlaylist',
                    'removeRecordingFromPlaylistSuccess',
                    'setRecordingMeta',
                    sessionRecordingDataLogic({
                        sessionRecordingId: 'nightly',
                        playerKey: 'test',
                    }).actionTypes.setRecordingMetaSuccess,
                ])
                .toMatchValues({
                    sessionPlayerMetaData: expect.objectContaining({
                        metadata: expect.objectContaining({
                            playlists: ['updated playlist'],
                        }),
                    }),
                })
        })
    })
})
