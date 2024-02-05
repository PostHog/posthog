import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'
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
        <div className="relative flex flex-col gap-6 p-3">
            <div className="space-y-1">
                {onReset && (
                    <span className="absolute top-2 right-2">
                        <LemonButton size="small" onClick={onReset}>
                            Reset
                        </LemonButton>
                    </span>
                )}

                <LemonLabel info="Show recordings where all of below filters match.">Find sessions by:</LemonLabel>

                <LemonSegmentedButton
                    size="small"
                    value={showAdvancedFilters ? 'advanced' : 'simple'}
                    options={[
                        {
                            value: 'simple',
                            label: 'Simple filters',
                            disabledReason: hasAdvancedFilters
                                ? 'You are only allowed person filters and a single pageview event (filtered by current url) to switch back to simple filters'
                                : undefined,
                        },
                        { value: 'advanced', label: 'Advanced filters' },
                    ]}
                    onChange={(newValue) => setShowAdvancedFilters(newValue === 'advanced')}
                    data-attr={`session-recordings-show-${showAdvancedFilters ? 'simple' : 'advanced'}-filters`}
                    fullWidth
                />
            </div>

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
        </div>
    )
}
