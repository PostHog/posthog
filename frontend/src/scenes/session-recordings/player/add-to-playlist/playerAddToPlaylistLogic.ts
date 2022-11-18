import { kea, props, path, key, actions, reducers, selectors, afterMount, connect } from 'kea'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import type { playerAddToPlaylistLogicType } from './playerAddToPlaylistLogicType'
import FuseClass from 'fuse.js'
import { Fuse } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { SavedSessionRecordingPlaylistsResult } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { toParams } from 'lib/utils'
import { savedSessionRecordingPlaylistModelLogic } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'

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
    connect(() => ({
        actions: [
            savedSessionRecordingPlaylistModelLogic,
            [
                'addRecordingToPlaylist',
                'addRecordingToPlaylistSuccess',
                'addRecordingToPlaylistFailure',
                'removeRecordingFromPlaylist',
                'removeRecordingFromPlaylistSuccess',
                'removeRecordingFromPlaylistFailure',
            ],
        ],
    })),
    actions(() => ({
        addNewPlaylist: true,
        setSearchQuery: (query: string) => ({ query }),
        setRecording: (recording: SessionRecordingType) => ({ recording }),
        setScrollIndex: (index: number) => ({ index }),
    })),
    loaders(({ values }) => ({
        playlistsResponse: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadPlaylists: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists(toParams({ static: true }))
                breakpoint()
                return response
            },
            addRecordingToPlaylistSuccess: ({ _recordingModel, payload }) => ({
                ...values.playlistsResponse,
                results: values.playlistsResponse.results.map((playlist) =>
                    payload?.playlist?.id === playlist.id
                        ? {
                              ...playlist,
                              playlist_items: [...(playlist.playlist_items ?? []), { id: _recordingModel.id }],
                          }
                        : playlist
                ),
            }),
            removeRecordingFromPlaylistSuccess: ({ _recordingModel, payload }) => ({
                ...values.playlistsResponse,
                results: values.playlistsResponse.results.map((playlist) =>
                    payload?.playlist?.id === playlist.id
                        ? {
                              ...playlist,
                              playlist_items: playlist.playlist_items?.filter((item) => item.id !== _recordingModel.id),
                          }
                        : playlist
                ),
            }),
        },
    })),
    reducers(() => ({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        scrollIndex: [-1 as number, { setScrollIndex: (_, { index }) => index }],
        playlistWithActiveAPICall: [
            null as number | null,
            {
                addRecordingToPlaylist: (_, { playlist }) => playlist.id,
                removeRecordingFromPlaylist: (_, { playlist }) => playlist.id,
                addRecordingToPlaylistSuccess: () => null,
                addRecordingToPlaylistFailure: () => null,
                removeRecordingFromPlaylistSuccess: () => null,
                removeRecordingFromPlaylistFailure: () => null,
            },
        ],
    })),
    selectors(({ props }) => ({
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
            (s) => [s.filteredPlaylists],
            (filteredPlaylists): SessionRecordingPlaylistType[] => [
                ...filteredPlaylists.filter((p: SessionRecordingPlaylistType) =>
                    p.playlist_items?.map((item) => item.id).includes(props.recording.id)
                ),
            ],
        ],
        orderedPlaylists: [
            (s) => [s.currentPlaylists, s.filteredPlaylists],
            (currentPlaylists, filteredPlaylists): SessionRecordingPlaylistType[] => {
                const currentPlaylistIds = new Set(currentPlaylists.map((cp) => cp.id))
                return [
                    ...currentPlaylists,
                    ...filteredPlaylists.filter((p: SessionRecordingPlaylistType) => !currentPlaylistIds.has(p.id)),
                ]
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadPlaylists({})
    }),
])
