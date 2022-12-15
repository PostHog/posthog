import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { EntityTypes, FilterType, LocalRecordingFilters, RecordingFilters } from '~/types'
import { useEffect, useState } from 'react'
import equal from 'fast-deep-equal'

interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
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
                type: EntityTypes.NEW_ENTITY,
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
        <>
            <div className="border rounded p-4">
                <div className="space-y-2">
                    <LemonLabel info="Show recordings where all of the events or actions listed below happen.">
                        Filter by events and actions
                    </LemonLabel>
                    <ActionFilter
                        bordered
                        filters={localFilters}
                        setFilters={(payload) => {
                            // reportRecordingsListFilterAdded(SessionRecordingFilterType.EventAndAction)
                            setLocalFilters(payload)
                        }}
                        typeKey={'session-recordings'}
                        mathAvailability={MathAvailability.None}
                        buttonCopy="Add filter"
                        hideRename
                        hideDuplicate
                        showNestedArrow={false}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Actions, TaxonomicFilterGroupType.Events]}
                        propertiesTaxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        propertyFiltersPopover
                    />
                </div>
                {showPropertyFilters && (
                    <div className="mt-4 space-y-2">
                        <LemonLabel info="Show recordings by persons who match the set criteria">
                            Filter by persons and cohorts
                        </LemonLabel>

                        <PropertyFilters
                            pageKey={'session-recordings'}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.PersonProperties,
                                TaxonomicFilterGroupType.Cohorts,
                            ]}
                            propertyFilters={filters.properties}
                            onChange={(properties) => {
                                // reportRecordingsListFilterAdded(SessionRecordingFilterType.PersonAndCohort)
                                setFilters({ properties })
                            }}
                        />
                    </div>
                )}
            </div>
        </>
    )
}
