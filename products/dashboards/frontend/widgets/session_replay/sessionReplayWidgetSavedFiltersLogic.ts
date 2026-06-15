import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { toParams } from 'lib/utils'

import type { SessionRecordingPlaylistType } from '~/types'

import type { sessionReplayWidgetSavedFiltersLogicType } from './sessionReplayWidgetSavedFiltersLogicType'

// Saved session replay filters are SessionRecordingPlaylist rows with type "filters".
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
    }),
    selectors({
        savedFilterOptions: [
            (s) => [s.savedFilters],
            (savedFilters): { value: string; label: string }[] =>
                savedFilters.map((filter) => ({
                    value: filter.short_id,
                    label: filter.name || filter.derived_name || 'Unnamed filter',
                })),
        ],
        // Single source for resolving a saved-filter short_id to its display label, shared by the
        // tile filter bar and the card header eyebrow.
        savedFilterLabelById: [
            (s) => [s.savedFilterOptions],
            (savedFilterOptions): Record<string, string> =>
                Object.fromEntries(savedFilterOptions.map((option) => [option.value, option.label])),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSavedFilters()
    }),
])
