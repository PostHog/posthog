import { expectLogic } from 'kea-test-utils'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import { playlistPopoverLogic } from 'scenes/session-recordings/player/playlist-popover/playlistPopoverLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingPlaylistType } from '~/types'

describe('playlistPopoverLogic', () => {
    let logic: ReturnType<typeof playlistPopoverLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
                '/api/projects/:team/session_recording_playlists': { results: [{ id: 12345, count: 1 }] },
            },
            delete: {
                // '/api/projects/:team/session_recordings/:id': {success: true},
            },
            post: {
                '/api/projects/997/session_recording_playlists/:playlist_id/recordings/:recording_id/': {},
            },
        })

        initKeaTests()
        logic = playlistPopoverLogic({ sessionRecordingId: '12345', playerKey: 'player1' })
        logic.mount()
    })

    it('loads playlist for recordings on mount', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadPlaylistsForRecording', 'loadPlaylistsForRecordingSuccess'])
            .toMatchValues({
                currentPlaylists: [{ id: 12345, count: 1 }],
                allPlaylists: [
                    {
                        playlist: {
                            count: 1,
                            id: 12345,
                        },
                        selected: true,
                    },
                ],
            })
    })

    it('updates all playlists when a new one is added', async () => {
        await expectLogic(logic, () => {
            // form submission always does these 4 actions
            logic.actions.addToPlaylist({ short_id: 'abcded' } as unknown as SessionRecordingPlaylistType)
            logic.actions.setNewFormShowing(false)
            logic.actions.resetNewPlaylist()
            logic.actions.setSearchQuery('')
        })
            // NB this is a surprising to me order of seeing these actions
            .toDispatchActions([
                'loadPlaylistsForRecording',
                'addToPlaylist',
                'addToPlaylistSuccess',
                'loadPlaylistsForRecordingSuccess',
            ])
            .toMatchValues({
                currentPlaylists: [{ id: 12345, count: 1 }, { id: 23456 }],
                allPlaylists: [
                    {
                        playlist: {
                            count: 1,
                            id: 12345,
                        },
                        selected: true,
                    },
                    {
                        playlist: {
                            id: 23456,
                        },
                        selected: true,
                    },
                ],
            })
    })
})
