import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { toParams } from 'lib/utils/url'

import type { SessionRecordingPlaylistType } from '~/types'

import type { sessionReplayWidgetSavedFiltersLogicType } from './sessionReplayWidgetSavedFiltersLogicType'

const toOptions = (
    playlists: SessionRecordingPlaylistType[],
    unnamedLabel: string
): { value: string; label: string }[] =>
    playlists.map((playlist) => ({
        value: playlist.short_id,
        label: playlist.name || playlist.derived_name || unnamedLabel,
    }))

// Saved session replay filters and collections are both SessionRecordingPlaylist rows, distinguished by
// type ("filters" vs "collection"). The widget can source recordings from either, so we load both here.
export const sessionReplayWidgetSavedFiltersLogic = kea<sessionReplayWidgetSavedFiltersLogicType>([
    path(['products', 'dashboards', 'widgets', 'session_replay', 'sessionReplayWidgetSavedFiltersLogic']),
    loaders({
        savedFilters: {
            __default: [] as SessionRecordingPlaylistType[],
            loadSavedFilters: async () => {
                const response = await api.recordings.listPlaylists(
                    toParams({ limit: 100, order: '-last_modified_at', type: 'filters' })
                )
                return response.results
            },
        },
        collections: {
            __default: [] as SessionRecordingPlaylistType[],
            loadCollections: async () => {
                const response = await api.recordings.listPlaylists(
                    toParams({ limit: 100, order: '-last_modified_at', type: 'collection' })
                )
                return response.results
            },
        },
    }),
    selectors({
        savedFilterOptions: [
            (s) => [s.savedFilters],
            (savedFilters): { value: string; label: string }[] => toOptions(savedFilters, 'Unnamed filter'),
        ],
        collectionOptions: [
            (s) => [s.collections],
            (collections): { value: string; label: string }[] => toOptions(collections, 'Unnamed collection'),
        ],
        // Single source for resolving a saved-filter short_id to its display label, shared by the
        // tile filter bar and the card header top heading.
        savedFilterLabelById: [
            (s) => [s.savedFilterOptions],
            (savedFilterOptions): Record<string, string> =>
                Object.fromEntries(savedFilterOptions.map((option) => [option.value, option.label])),
        ],
        collectionLabelById: [
            (s) => [s.collectionOptions],
            (collectionOptions): Record<string, string> =>
                Object.fromEntries(collectionOptions.map((option) => [option.value, option.label])),
        ],
    }),
    afterMount(({ actions, cache }) => {
        actions.loadSavedFilters()
        actions.loadCollections()
        // The "Create a collection / saved filter" shortcuts open session replay in a new tab. Reload both
        // lists when the user returns so a just-created collection/filter is selectable without a page refresh.
        cache.disposables.add(
            () => {
                const handler = (): void => {
                    if (document.visibilityState === 'visible') {
                        actions.loadSavedFilters()
                        actions.loadCollections()
                    }
                }
                document.addEventListener('visibilitychange', handler)
                return () => document.removeEventListener('visibilitychange', handler)
            },
            'reloadOnTabFocus',
            { pauseOnPageHidden: false }
        )
    }),
])
