import { LemonButton } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useEffect, useState } from 'react'

import { EntityTypes, FilterType, LocalRecordingFilters, RecordingFilters } from '~/types'

import { AdvancedSessionRecordingsFilters } from './AdvancedSessionRecordingsFilters'
import { SimpleSessionRecordingsFilters } from './SimpleSessionRecordingsFilters'

interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    simpleFilters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    setSimpleFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
    onReset?: () => void
}

const filtersToLocalFilters = (filters: RecordingFilters): LocalRecordingFilters => {
    return {
        actions: filters.actions || [],
        events: filters.events || [],
    }
}

export function SessionRecordingsFilters({
    filters,
    simpleFilters,
    setFilters,
    setSimpleFilters,
    showPropertyFilters,
    onReset,
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
        <div className="relative flex flex-col">
            <div className="space-y-1 p-3">
                <div className="flex justify-between">
                    <LemonLabel>Find sessions:</LemonLabel>

                    {onReset && (
                        <span className="absolute top-2 right-2">
                            <LemonButton size="small" onClick={onReset}>
                                Reset
                            </LemonButton>
                        </span>
                    )}
                </div>

                <SimpleSessionRecordingsFilters
                    filters={simpleFilters}
                    setFilters={setSimpleFilters}
                    localFilters={localFilters}
                    setLocalFilters={setLocalFilters}
                />
            </div>

            <AdvancedSessionRecordingsFilters
                filters={filters}
                setFilters={setFilters}
                localFilters={localFilters}
                setLocalFilters={setLocalFilters}
                showPropertyFilters={showPropertyFilters}
            />
        </div>
    )
}
