import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { RecordingUniversalFilters } from '~/types'

import { updatePlaylist } from './playlistUtils'
import { stripSessionIds } from './playlistUtils'

/** Shown while the applied saved filter differs from the list's filters: update it, save a copy, or revert. */
export function SavedFilterEditedBar({
    filters,
    setFilters,
    onSaveAsCopy,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    onSaveAsCopy: () => void
}): JSX.Element | null {
    const { appliedSavedFilter, playlistsLoading } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFilters, setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)
    if (!appliedSavedFilter) {
        return null
    }

    const update = async (): Promise<void> => {
        const updated = await updatePlaylist(
            appliedSavedFilter.short_id,
            { filters: stripSessionIds(filters), type: 'filters' },
            false
        )
        loadSavedFilters()
        setAppliedSavedFilter(updated)
    }

    return (
        <div
            className="flex items-center gap-2 flex-wrap rounded border border-warning bg-warning-highlight px-2 py-1 text-xs"
            data-attr="list-saved-filter-edited"
        >
            <span className="text-secondary">Saved filter changed.</span>
            <LemonButton
                size="xsmall"
                type="secondary"
                loading={playlistsLoading}
                onClick={() => void update()}
                className="max-w-60"
                truncate
                data-attr="list-saved-filter-update"
            >
                Update "{appliedSavedFilter.name || 'Unnamed'}"
            </LemonButton>
            <LemonButton size="xsmall" onClick={onSaveAsCopy} data-attr="list-saved-filter-save-copy">
                Save as copy
            </LemonButton>
            <LemonButton
                size="xsmall"
                onClick={() =>
                    setFilters(stripSessionIds(appliedSavedFilter.filters as Partial<RecordingUniversalFilters>))
                }
                data-attr="list-saved-filter-revert"
            >
                Revert
            </LemonButton>
        </div>
    )
}
