import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function useListTroubleshooting(): {
    heading: string
    recordingsAreHidden: boolean
    hiddenRecordingsCount: number
    canClearFilters: boolean
    showHiddenRecordings: () => void
    clearFilters: () => void
    searchLast30Days: () => void
} {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const { hiddenRecordingsCount, totalFiltersCount, isScopedByCaller } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters, resetFilters } = useActions(sessionRecordingsPlaylistLogic)

    const hasFilters = totalFiltersCount > 0

    useEffect(() => {
        posthog.capture('recording list empty state shown', {
            hidden_recordings_count: hiddenRecordingsCount,
            total_filters_count: totalFiltersCount,
        })
    }, [])

    return {
        heading: hasFilters ? 'No recordings match your filters' : 'No recordings found',
        recordingsAreHidden: hideViewedRecordings !== false,
        hiddenRecordingsCount,
        // Clearing would drop the caller's scoping, leaving a list that no longer matches the surface.
        canClearFilters: hasFilters && !isScopedByCaller,
        showHiddenRecordings: () => {
            setShowSettings(true)
            setHideViewedRecordings(false)
        },
        clearFilters: () => resetFilters(),
        searchLast30Days: () => setFilters({ date_from: '-30d' }),
    }
}
