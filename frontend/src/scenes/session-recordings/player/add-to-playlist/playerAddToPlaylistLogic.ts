import { kea, props, path, key, actions, reducers, selectors, listeners, afterMount } from 'kea'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import type { playerAddToPlaylistLogicType } from './playerAddToPlaylistLogicType'
import FuseClass from 'fuse.js'
import { Fuse } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { SavedSessionRecordingPlaylistsResult } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { toParams } from 'lib/utils'
import { lemonToast } from 'lib/components/lemonToast'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { updateRecording } from 'scenes/session-recordings/playlist/playlistUtils'

export interface PlayerAddToPlaylistLogicProps {
    recording: Pick<SessionRecordingType, 'id' | 'playlists' | 'start_time'>
}

export const playerAddToPlaylistLogic = kea<playerAddToPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'add-to-playlist', 'playerAddToPlaylistLogic', key]),
    props({} as PlayerAddToPlaylistLogicProps),
    key(({ recording }) => {
        if (!recording.id) {
            throw Error('must provide an insight with a short id')
        }
        return recording.id
    }),
    actions(() => ({
        addNewPlaylist: true,
        setSearchQuery: (query: string) => ({ query }),
        setRecording: (recording: SessionRecordingType) => ({ recording }),
        setScrollIndex: (index: number) => ({ index }),
        addToPlaylist: (playlist: Pick<SessionRecordingPlaylistType, 'id' | 'short_id'>) => ({ playlist }),
        removeFromPlaylist: (playlist: Pick<SessionRecordingPlaylistType, 'id' | 'short_id'>) => ({ playlist }),
    })),
    loaders(() => ({
        playlistsResponse: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadPlaylists: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(toParams({ static: true }))
                breakpoint()
                return response
            },
        },
    })),
    reducers(() => ({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        playlistWithActiveAPICall: [
            null as number | null,
            {
                addToPlaylist: (_, { playlist }) => playlist.id,
                removeFromPlaylist: (_, { playlist }) => playlist.id,
                updateInsightSuccess: () => null,
                updateInsightFailure: () => null,
            },
        ],
    })),
    selectors(() => ({
        playlistsFuse: [
            (s) => [s.playlistsResponse],
            (playlistsResponse): Fuse => {
                return new FuseClass(playlistsResponse.results || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],
        filteredPlaylists: [
            (s) => [s.searchQuery, s.playlistsFuse, s.playlistsResponse],
            (searchQuery, playlistsFuse, playlistsResponse): SessionRecordingPlaylistType[] =>
                searchQuery.length
                    ? playlistsFuse
                          .search(searchQuery)
                          .map((r: FuseClass.FuseResult<SessionRecordingPlaylistType>) => r.item)
                    : playlistsResponse.results || [],
        ],
        currentPlaylists: [
            (s) => [s.filteredPlaylists, (_, props) => props.playlists],
            (filteredPlaylists, playlists): SessionRecordingPlaylistType[] => [
                ...filteredPlaylists.filter((p: SessionRecordingPlaylistType) => playlists?.includes(p.id)),
            ],
        ],
        orderedPlaylists: [
            (s) => [s.currentPlaylists, s.filteredPlaylists, (_, props) => props.playlists],
            (currentPlaylists, filteredPlaylists, playlists): SessionRecordingPlaylistType[] => [
                ...currentPlaylists,
                ...filteredPlaylists.filter((p: SessionRecordingPlaylistType) => !playlists?.includes(p.id)),
            ],
        ],
    })),
    listeners(({ props }) => ({
        addToPlaylist: async ({ playlist }) => {
            const recording = {
                id: props.recording.id,
                playlists: [...(props.recording.playlists || []).filter((id) => id !== playlist.id), playlist.id],
            }
            const params = {
                recording_start_time: props.recording.start_time,
            }
            await updateRecording(recording, params, () => {
                lemonToast.success('Recording added to playlist', {
                    button: {
                        label: 'View playlist',
                        action: () => router.actions.push(urls.sessionRecordingPlaylist(playlist.short_id)),
                    },
                })
            })
        },
        removeFromPlaylist: async ({ playlist }): Promise<void> => {
            const recording = {
                id: props.recording.id,
                playlists: [...(props.recording.playlists || []).filter((id) => id !== playlist.id)],
            }
            const params = {
                recording_start_time: props.recording.start_time,
            }
            await updateRecording(recording, params, () => {
                lemonToast.success('Recording removed to playlist')
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlaylists({})
    }),
])
