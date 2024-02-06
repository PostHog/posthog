import { LemonButton } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useEffect, useState } from 'react'

import { EntityTypes, FilterType, LocalRecordingFilters, RecordingFilters } from '~/types'

import { AdvancedSessionRecordingsFilters } from './AdvancedSessionRecordingsFilters'
import { SimpleSessionRecordingsFilters } from './SimpleSessionRecordingsFilters'

interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
    onReset?: () => void
    hasAdvancedFilters: boolean
    showAdvancedFilters: boolean
    setShowAdvancedFilters: (showAdvancedFilters: boolean) => void
}

const filtersToLocalFilters = (filters: RecordingFilters): LocalRecordingFilters => {
    if (filters.actions?.length || filters.events?.length) {
        return {
            actions: filters.actions,
            events: filters.events,
        }
    }

    return {
        actions: [],
        events: [],
        new_entity: [
            {
                id: 'empty',
                type: EntityTypes.EVENTS,
                order: 0,
                name: 'empty',
            },
        ],
    }
}

export function SessionRecordingsFilters({
    filters,
    setFilters,
    showPropertyFilters,
    onReset,
    hasAdvancedFilters,
    showAdvancedFilters,
    setShowAdvancedFilters,
}: SessionRecordingsFiltersProps): JSX.Element {
    const [localFilters, setLocalFilters] = useState<FilterType>(filtersToLocalFilters(filters))

    // We have a copy of the filters as local state as it stores more properties than we want for playlists
    useEffect(() => {
        if (!equal(filters.actions, localFilters.actions) || !equal(filters.events, localFilters.events)) {
            setFilters({
                actions: localFilters.actions,
                events: localFilters.events,
            })
        }
    }, [localFilters])

    useEffect(() => {
        // We have a copy of the filters as local state as it stores more properties than we want for playlists
        // if (!equal(filters.actions, localFilters.actions) || !equal(filters.events, localFilters.events)) {
        if (!equal(filters.actions, localFilters.actions) || !equal(filters.events, localFilters.events)) {
            setLocalFilters(filtersToLocalFilters(filters))
        }
    }, [filters])

    return (
        <div className="relative flex flex-col gap-4 p-3">
            <div className="space-y-1">
                <div className="flex justify-between">
                    <LemonLabel>Find sessions by:</LemonLabel>
                </div>
            </div>

            {showAdvancedFilters ? (
                <>
                    <AdvancedSessionRecordingsFilters
                        filters={filters}
                        setFilters={setFilters}
                        localFilters={localFilters}
                        setLocalFilters={setLocalFilters}
                        showPropertyFilters={showPropertyFilters}
                    />
                    <LemonButton onClick={() => setShowAdvancedFilters(false)}>Show simple filters</LemonButton>
                </>
            ) : (
                <div className="space-y-2">
                    <SimpleSessionRecordingsFilters
                        filters={filters}
                        setFilters={setFilters}
                        localFilters={localFilters}
                        setLocalFilters={setLocalFilters}
                        onClickAdvancedFilters={() => setShowAdvancedFilters(true)}
                    />
                </div>
            )}
        </div>
    )
}
