import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Button } from '@posthog/quill'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
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
            <span className="text-muted-foreground">Saved filter changed.</span>
            <Button
                variant="outline"
                loading={updating}
                onClick={() => void update()}
                className="max-w-60"
                data-attr="list-saved-filter-update"
            >
                <span className="truncate">Update "{appliedSavedFilter.name || 'Unnamed'}"</span>
            </Button>
            <Button onClick={onSaveAsCopy} data-attr="list-saved-filter-save-copy">
                Save as copy
            </Button>
            <Button
                onClick={() => {
                    if (appliedSavedFilterFilters) {
                        applySavedFilter(appliedSavedFilterFilters)
                    }
                }}
                data-attr="list-saved-filter-revert"
            >
                Revert
            </Button>
        </div>
    )
}
