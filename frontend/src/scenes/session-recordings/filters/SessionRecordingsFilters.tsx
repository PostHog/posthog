import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { EntityTypes, FilterType, LocalRecordingFilters, RecordingFilters } from '~/types'
import { useEffect, useState } from 'react'
import equal from 'fast-deep-equal'
import { LemonButton } from '@posthog/lemon-ui'
import { SimpleSessionRecordingsFilters } from './SimpleSessionRecordingsFilters'
import { AdvancedSessionRecordingsFilters } from './AdvancedSessionRecordingsFilters'
interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
    onReset?: () => void
    showAdvancedFilters: boolean
    toggleAdvancedFilters: () => void
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
    showAdvancedFilters,
    toggleAdvancedFilters,
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
        <div className="relative flex flex-col gap-2 p-3 bg-side border-b">
            {onReset && (
                <span className="absolute top-2 right-2">
                    <LemonButton size="small" onClick={onReset}>
                        Reset
                    </LemonButton>
                </span>
            )}

            <LemonLabel info="Show recordings where all of below filters match.">Find sessions by:</LemonLabel>

            {showAdvancedFilters ? (
                <AdvancedSessionRecordingsFilters
                    filters={filters}
                    setFilters={setFilters}
                    localFilters={localFilters}
                    setLocalFilters={setLocalFilters}
                    showPropertyFilters={showPropertyFilters}
                />
            ) : (
                <SimpleSessionRecordingsFilters
                    filters={filters}
                    setFilters={setFilters}
                    localFilters={localFilters}
                    setLocalFilters={setLocalFilters}
                />
            )}

            <div>
                <LemonButton size="small" onClick={toggleAdvancedFilters}>
                    Switch to {showAdvancedFilters ? 'simple filters' : 'advanced filters'}
                </LemonButton>
            </div>
        </div>
    )
}
