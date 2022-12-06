import { kea, props, path, key, actions, reducers, selectors, afterMount, connect, listeners } from 'kea'
import { SessionRecordingPlaylistType } from '~/types'
import type { playerAddToPlaylistLogicType } from './playerAddToPlaylistLogicType'
import FuseClass from 'fuse.js'
import { Fuse } from 'lib/components/AddToDashboard/addToDashboardModalLogic'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { SavedSessionRecordingPlaylistsResult } from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistsLogic'
import { toParams } from 'lib/utils'
import {
    PlaylistTypeWithIds,
    savedSessionRecordingPlaylistModelLogic,
} from 'scenes/session-recordings/saved-playlists/savedSessionRecordingPlaylistModelLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'

export const playerAddToPlaylistLogic = kea<playerAddToPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'add-to-playlist', 'playerAddToPlaylistLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect(({ sessionRecordingId, recordingStartTime }: SessionRecordingPlayerLogicProps) => ({
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
            sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }),
            ['setRecordingMeta'],
        ],
        values: [sessionRecordingDataLogic({ sessionRecordingId, recordingStartTime }), ['sessionPlayerMetaData']],
    })),
    actions(() => ({
        setSearchQuery: (query: string) => ({ query }),
        addToPlaylist: (playlist: PlaylistTypeWithIds) => ({ playlist }),
        removeFromPlaylist: (playlist: PlaylistTypeWithIds) => ({ playlist }),
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
    listeners(({ actions, values, props }) => ({
        addToPlaylist: async ({ playlist }) => {
            actions.addRecordingToPlaylist(
                {
                    id: props.sessionRecordingId,
                    playlists: values.recordingPlaylists,
                },
                playlist
            )
        },
        addRecordingToPlaylistSuccess: ({ _recordingModel, payload }) => {
            if (_recordingModel.playlists) {
                actions.setRecordingMeta({
                    metadata: {
                        ...values.sessionPlayerMetaData.metadata,
                        playlists: [..._recordingModel.playlists],
                    },
                })
                // Update playlist if playlist detail page is mounted
                payload?.playlist?.short_id &&
                    sessionRecordingsPlaylistLogic
                        .findMounted({ shortId: payload.playlist.short_id })
                        ?.actions?.getPlaylist()
            }
        },
        removeFromPlaylist: async ({ playlist }) => {
            actions.removeRecordingFromPlaylist(
                {
                    id: props.sessionRecordingId,
                    playlists: values.recordingPlaylists,
                },
                playlist
            )
        },
        removeRecordingFromPlaylistSuccess: ({ _recordingModel, payload }) => {
            if (_recordingModel.playlists) {
                actions.setRecordingMeta({
                    metadata: {
                        ...values.sessionPlayerMetaData.metadata,
                        playlists: [..._recordingModel.playlists],
                    },
                })
                // Update playlist if playlist detail page is mounted
                payload?.playlist?.short_id &&
                    sessionRecordingsPlaylistLogic
                        .findMounted({ shortId: payload.playlist.short_id })
                        ?.actions?.getPlaylist()
            }
        },
    })),
    selectors(() => ({
        recordingPlaylists: [
            (s) => [s.sessionPlayerMetaData],
            (sessionPlayerMetaData) => sessionPlayerMetaData.metadata?.playlists ?? [],
        ],
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
            (s) => [s.filteredPlaylists, s.recordingPlaylists],
            (filteredPlaylists, recordingPlaylists): SessionRecordingPlaylistType[] => [
                ...filteredPlaylists.filter((p: SessionRecordingPlaylistType) => recordingPlaylists.includes(p.id)),
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
