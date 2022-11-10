import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { Breadcrumb, RecordingFilters, SessionRecordingPlaylistType, SessionRecordingsTabs } from '~/types'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import type { sessionRecordingsPlaylistLogicType } from './sessionRecordingsPlaylistLogicType'
import { urls } from 'scenes/urls'
import equal from 'fast-deep-equal'
import { lemonToast } from '@posthog/lemon-ui'
import { beforeUnload, router } from 'kea-router'
import { cohortsModel } from '~/models/cohortsModel'
import { openBillingPopupModal } from 'scenes/billing/v2/BillingPopup'
import { PLAYLIST_LIMIT_REACHED_MESSAGE } from 'scenes/session-recordings/sessionRecordingsLogic'
import { summarizePlaylistFilters } from 'scenes/session-recordings/playlist/playlistUtils'

export async function createPlaylist(
    playlist: Partial<SessionRecordingPlaylistType>
): Promise<SessionRecordingPlaylistType | null> {
    try {
        return await api.recordings.createPlaylist(playlist)
    } catch (e: any) {
        if (e.status === 403) {
            openBillingPopupModal({
                title: `Upgrade now to unlock unlimited playlists`,
                description: PLAYLIST_LIMIT_REACHED_MESSAGE,
            })
        } else {
            throw e
        }
    }
    return null
}

export interface SessionRecordingsPlaylistLogicProps {
    shortId: string
}

export const sessionRecordingsPlaylistLogic = kea<sessionRecordingsPlaylistLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsPlaylistLogic', key]),
    props({} as SessionRecordingsPlaylistLogicProps),
    key((props) => props.shortId),
    connect({
        values: [cohortsModel, ['cohortsById']],
    }),
    actions({
        loadPlaylist: true,
        setFilters: (filters: RecordingFilters | null) => ({ filters }),
        saveChanges: true,
        duplicatePlaylist: true,
    }),
    loaders(({ props, values }) => ({
        playlist: [
            null as SessionRecordingPlaylistType | null,
            {
                loadPlaylist: async () => {
                    return api.recordings.getPlaylist(props.shortId)
                },

                updatePlaylist: async (playlist: Partial<SessionRecordingPlaylistType>, breakpoint) => {
                    await breakpoint(100)
                    const response = api.recordings.updatePlaylist(props.shortId, {
                        ...playlist,
                        derived_name: values.derivedName, // Makes sure derived name is kept up to date
                    })
                    breakpoint()

                    lemonToast.success('Playlist updated successfully')

                    return response
                },
            },
        ],
    })),

    reducers(({}) => ({
        filters: [
            null as RecordingFilters | null,
            {
                loadPlaylistSuccess: (_, { playlist }) => playlist.filters || null,
                setFilters: (_, { filters }) => filters,
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        saveChanges: async () => {
            actions.updatePlaylist({ filters: values.filters || undefined })
        },

        duplicatePlaylist: async () => {
            if (!values.playlist) {
                return
            }

            const { id, short_id, ...playlist } = values.playlist
            playlist.name = playlist.name ? playlist.name + ' (copy)' : ''
            playlist.derived_name = playlist.derived_name ? playlist.derived_name + ' (copy)' : ''

            const newPlaylist = await createPlaylist(playlist)
            if (!newPlaylist) {
                return
            }
            lemonToast.success('Playlist duplicated successfully')
            router.actions.push(urls.sessionRecordingPlaylist(newPlaylist.short_id))
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: () => values.hasChanges,
        message: 'Leave playlist? Changes you made will be discarded.',
        onConfirm: () => {
            actions.setFilters(values.playlist?.filters || null)
        },
    })),

    selectors(({}) => ({
        breadcrumbs: [
            (s) => [s.playlist],
            (playlist): Breadcrumb[] => [
                {
                    name: 'Saved Playlists',
                    path: urls.sessionRecordings(SessionRecordingsTabs.Playlists),
                },
                {
                    name: playlist?.name || playlist?.derived_name || 'Untitled Playlist',
                    path: urls.sessionRecordingPlaylist(playlist?.short_id || ''),
                },
            ],
        ],
        hasChanges: [
            (s) => [s.playlist, s.filters],
            (playlist, filters): boolean => !equal(playlist?.filters, filters),
        ],
        derivedName: [
            (s) => [s.filters, s.cohortsById],
            (filters, cohortsById) => summarizePlaylistFilters(filters || {}, cohortsById).slice(0, 400),
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadPlaylist()
    }),
])
