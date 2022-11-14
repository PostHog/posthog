import { kea, props, path, key, actions, reducers, selectors, listeners } from 'kea'
import { SessionRecordingPlaylistType, SessionRecordingType } from '~/types'
import type { playerAddToPlaylistLogicType } from './playerAddToPlaylistLogicType'
import FuseClass from 'fuse.js'
import { Fuse } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { SavedSessionRecordingPlaylistsResult } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'

export interface PlayerAddToPlaylistLogicProps {
    id: SessionRecordingType['id']
    playlists: SessionRecordingType['playlists']
}

export const playerAddToPlaylistLogic = kea<playerAddToPlaylistLogicType>([
    path(['scenes', 'session-recordings', 'player', 'add-to-playlist', 'playerAddToPlaylistLogic']),
    props({} as PlayerAddToPlaylistLogicProps),
    key((id) => `${id}`),
    actions(() => ({
        addNewPlaylist: true,
        setSearchQuery: (query: string) => ({ query }),
        setRecording: (recording: SessionRecordingType) => ({ recording }),
        setScrollIndex: (index: number) => ({ index }),
        addToPlaylist: (playlistId: number) => ({ playlistId }),
        removeFromPlaylist: (playlistId: number) => ({ playlistId }),
    })),
    loaders(() => ({
        playlistsResponse: {
            __default: { results: [], count: 0, filters: null } as SavedSessionRecordingPlaylistsResult,
            loadPlaylists: async (_, breakpoint) => {
                await breakpoint(300)
                const response = await api.recordings.listPlaylists('')
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
                addToPlaylist: (_, { playlistId }) => playlistId,
                removeFromPlaylist: (_, { playlistId }) => playlistId,
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
    listeners(() => ({
        addToPlaylist: async () => {
            // update recording
        },
        removeFromPlaylist: async (): Promise<void> => {
            // update recording
        },
    })),
])
