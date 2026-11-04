import { useActions, useValues } from 'kea'

import { Toggle } from '@posthog/quill'

import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { SessionRecordingPlaylistType } from '~/types'

import { stripSessionIds } from './playlistUtils'
import { asUniversalFilters, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

// The select beside the chips lists every saved filter, so only the first few get a chip.
const MAX_CHIPS = 4

export function SavedFilterChips({ edited }: { edited: boolean }): JSX.Element | null {
    const { savedFilters, appliedSavedFilter } = useValues(sessionRecordingSavedFiltersLogic)
    const { setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)
    const { applySavedFilter } = useActions(sessionRecordingsPlaylistLogic)

    if (savedFilters.results.length === 0) {
        return null
    }

    const apply = (filter: SessionRecordingPlaylistType): void => {
        const universal = asUniversalFilters(filter.filters)
        if (!universal) {
            return
        }
        applySavedFilter(stripSessionIds(universal))
        setAppliedSavedFilter(filter)
    }

    return (
        <>
            {savedFilters.results.slice(0, MAX_CHIPS).map((filter) => (
                <Toggle
                    key={filter.short_id}
                    variant="outline"
                    pressed={!edited && filter.short_id === appliedSavedFilter?.short_id}
                    onPressedChange={() => apply(filter)}
                    className="max-w-60"
                    data-attr="list-saved-filter-chip"
                >
                    <span className="truncate">{filter.name || filter.derived_name || 'Unnamed'}</span>
                </Toggle>
            ))}
        </>
    )
}
