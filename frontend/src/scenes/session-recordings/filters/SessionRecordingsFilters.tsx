import { LemonButton } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { useEffect, useState } from 'react'

import { EntityTypes, FilterType, LocalRecordingFilters, RecordingFilters } from '~/types'

import { SessionFilterMode } from '../player/playerSettingsLogic'
import { AdvancedSessionRecordingsFilters } from './AdvancedSessionRecordingsFilters'
import { SimpleSessionRecordingsFilters } from './SimpleSessionRecordingsFilters'

interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
    onReset?: () => void
    filterMode: SessionFilterMode
    setFilterMode: (mode: SessionFilterMode) => void
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
    filterMode,
    setFilterMode,
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
        <div className="relative flex flex-col p-3">
            <div className="space-y-1">
                <div className="flex justify-between">
                    <LemonLabel>Find sessions:</LemonLabel>

                    {filterMode === 'advanced' && onReset && (
                        <span className="absolute top-2 right-2">
                            <LemonButton
                                size="small"
                                onClick={() => {
                                    onReset()
                                    setFilterMode('simple')
                                }}
                            >
                                Reset
                            </LemonButton>
                        </span>
                    )}
                </div>
            </div>

            {filterMode === 'advanced' ? (
                <AdvancedSessionRecordingsFilters
                    filters={filters}
                    setFilters={setFilters}
                    localFilters={localFilters}
                    setLocalFilters={setLocalFilters}
                    showPropertyFilters={showPropertyFilters}
                />
            ) : (
                <div className="space-y-2">
                    <SimpleSessionRecordingsFilters
                        filters={filters}
                        setFilters={setFilters}
                        localFilters={localFilters}
                        setLocalFilters={setLocalFilters}
                        onClickAdvancedFilters={() => setFilterMode('advanced')}
                    />
                </div>
            )}
        </div>
    )
}
