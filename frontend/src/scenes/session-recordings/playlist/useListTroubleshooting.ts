import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { defaultRecordingDurationFilter, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export function useListTroubleshooting(): {
    heading: string
    recordingsAreHidden: boolean
    hiddenRecordingsCount: number
    activityFilterHidesRecordings: boolean
    activityFilterHiddenRecordingsCount: number
    activityFilterHiddenRecordingsLabel: string
    hasMoreActivityFilterHiddenRecordings: boolean
    canClearFilters: boolean
    showHiddenRecordings: () => void
    showRecordingsHiddenByActivityFilter: () => void
    clearFilters: () => void
    searchLast30Days: () => void
} {
    const { hideViewedRecordings } = useValues(playerSettingsLogic)
    const { setHideViewedRecordings } = useActions(playerSettingsLogic)
    const {
        hiddenRecordingsCount,
        recordingsHiddenByActivityFilterCount,
        hasMoreRecordingsHiddenByActivityFilter,
        activityFilterHidesRecordings,
        totalFiltersCount,
        isScopedByCaller,
    } = useValues(sessionRecordingsPlaylistLogic)
    const { setShowSettings, setFilters, resetFilters } = useActions(sessionRecordingsPlaylistLogic)

    const hasFilters = totalFiltersCount > 0

    // The filter is labelled by its threshold in the filter bar ("active seconds"), so the
    // offer names that rather than an "activity filter" the viewer never sees. The button
    // only renders when the count is above zero, so the label needs no empty case.
    const activityFilterHiddenRecordingsLabel = `Show ${recordingsHiddenByActivityFilterCount}${
        hasMoreRecordingsHiddenByActivityFilter ? '+' : ''
    } recording${
        recordingsHiddenByActivityFilterCount === 1 && !hasMoreRecordingsHiddenByActivityFilter ? '' : 's'
    } shorter than ${defaultRecordingDurationFilter.value} active seconds`

    useEffect(() => {
        posthog.capture('recording list empty state shown', {
            hidden_recordings_count: hiddenRecordingsCount,
            activity_filter_hides_recordings: recordingsHiddenByActivityFilterCount > 0,
            total_filters_count: totalFiltersCount,
        })
    }, [])

    return {
        heading: hasFilters ? 'No recordings match your filters' : 'No recordings found',
        recordingsAreHidden: hideViewedRecordings !== false,
        hiddenRecordingsCount,
        activityFilterHidesRecordings,
        activityFilterHiddenRecordingsCount: recordingsHiddenByActivityFilterCount,
        activityFilterHiddenRecordingsLabel,
        hasMoreActivityFilterHiddenRecordings: hasMoreRecordingsHiddenByActivityFilter,
        // Clearing would drop the caller's scoping, leaving a list that no longer matches the surface.
        canClearFilters: hasFilters && !isScopedByCaller,
        showHiddenRecordings: () => {
            setShowSettings(true)
            setHideViewedRecordings(false)
        },
        showRecordingsHiddenByActivityFilter: () => setFilters({ duration: [] }),
        clearFilters: () => resetFilters(),
        searchLast30Days: () => setFilters({ date_from: '-30d' }),
    }
}
