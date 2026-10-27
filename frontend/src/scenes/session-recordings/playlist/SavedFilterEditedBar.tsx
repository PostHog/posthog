import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { sessionRecordingSavedFiltersLogic } from 'scenes/session-recordings/filters/sessionRecordingSavedFiltersLogic'

import { RecordingUniversalFilters } from '~/types'

import { updatePlaylist } from './playlistUtils'
import { stripSessionIds } from './playlistUtils'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function SavedFilterEditedBar({
    filters,
    onSaveAsCopy,
}: {
    filters: RecordingUniversalFilters
    onSaveAsCopy: () => void
}): JSX.Element | null {
    const { appliedSavedFilter, appliedSavedFilterFilters } = useValues(sessionRecordingSavedFiltersLogic)
    const { loadSavedFilters, setAppliedSavedFilter } = useActions(sessionRecordingSavedFiltersLogic)
    const { applySavedFilter } = useActions(sessionRecordingsPlaylistLogic)
    const [updating, setUpdating] = useState(false)
    if (!appliedSavedFilter) {
        return null
    }

    const update = async (): Promise<void> => {
        setUpdating(true)
        try {
            const updated = await updatePlaylist(
                appliedSavedFilter.short_id,
                { filters: stripSessionIds(filters), type: 'filters' },
                false
            )
            loadSavedFilters()
            setAppliedSavedFilter(updated)
        } catch {
            lemonToast.error('Could not update the saved filter. Please try again.')
        } finally {
            setUpdating(false)
        }
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
                loading={updating}
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
                onClick={() => {
                    if (appliedSavedFilterFilters) {
                        applySavedFilter(appliedSavedFilterFilters)
                    }
                }}
                data-attr="list-saved-filter-revert"
            >
                Revert
            </LemonButton>
        </div>
    )
}
