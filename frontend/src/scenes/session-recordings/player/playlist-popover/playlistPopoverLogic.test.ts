import { expectLogic } from 'kea-test-utils'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import { playlistPopoverLogic } from 'scenes/session-recordings/player/playlist-popover/playlistPopoverLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingPlaylistType } from '~/types'

function makePlaylist(id: number, name: string): SessionRecordingPlaylistType {
    return {
        id: id,
        short_id: id.toString(),
        name: name,
    } as Partial<SessionRecordingPlaylistType> as SessionRecordingPlaylistType
}

const test_playlist = makePlaylist(12345, 'a test playlist')
const abc_playlist = makePlaylist(23456, 'abc')
const cde_playlist = makePlaylist(345, 'cde')
const unselected_playlists = [test_playlist, abc_playlist, cde_playlist]
const selected_playlist = makePlaylist(54321, 'a playlist that has this recording in it')

describe('playlistPopoverLogic', () => {
    let logic: ReturnType<typeof playlistPopoverLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id': recordingMetaJson,
                '/api/projects/:team/session_recording_playlists': (req, res, ctx) => {
                    if (req.url.searchParams.get('search') === 'test') {
                        return res(ctx.json({ results: [test_playlist] }))
                    }
                    if (req.url.searchParams.get('session_recording_id') === '12345') {
                        return res(ctx.json({ results: [selected_playlist] }))
                    }
                    return res(ctx.json({ results: [...unselected_playlists, selected_playlist] }))
                },
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

    it('loads playlist data when expected', async () => {
        // we don't load data on mount
        expectLogic(logic)
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['loadPlaylistsSuccess'])
            .toMatchValues({ playlists: [], unselectedPlaylists: [], currentPlaylists: [], allPlaylists: [] })

        // we load playlists when the popover is shown
        expectLogic(logic, () => {
            logic.actions.setShowPlaylistPopover(true)
        })
            .toDispatchActions([
                'loadPlaylists',
                'loadPlaylistsSuccess',
                'loadPlaylistsForRecording',
                'loadPlaylistsForRecordingSuccess',
            ])
            .toMatchValues({
                playlists: [...unselected_playlists, selected_playlist],
                currentPlaylists: [selected_playlist],
                unselectedPlaylists: unselected_playlists,
                allPlaylists: [
                    {
                        playlist: { ...selected_playlist },
                        selected: true,
                    },
                    ...unselected_playlists.map((playlist) => ({
                        playlist: { ...playlist },
                        selected: false,
                    })),
                ],
            })
    })

    it('setting search query loads playlists', async () => {
        // after setting search query, only the matching playlists are loaded
        expectLogic(logic, () => {
            logic.actions.setSearchQuery('test')
        })
            .toDispatchActions(['loadPlaylists', 'loadPlaylistsSuccess'])
            .toMatchValues({ playlists: [test_playlist] })
    })

    it.skip('updates all playlists when a new one is added', async () => {
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
