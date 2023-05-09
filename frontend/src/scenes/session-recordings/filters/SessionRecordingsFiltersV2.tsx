import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { EntityTypes, FilterType, LocalRecordingFilters, RecordingDurationFilter, RecordingFilters } from '~/types'
import { useEffect, useState } from 'react'
import equal from 'fast-deep-equal'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationFilter } from './DurationFilter'

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

export function SessionRecordingsFiltersV2({
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
        <div className="flex flex-col gap-2 p-3 bg-side border-b">
            {/* This search is basically a helper to prefill the advanced options */}
            {/* <LemonInput size="small" placeholder="Search pageviews" /> */}

            <LemonLabel>Time and duration</LemonLabel>
            <div className="flex flex-wrap gap-2">
                <DateFilter
                    dateFrom={filters.date_from ?? '-7d'}
                    dateTo={filters.date_to ?? undefined}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setFilters({
                            date_from: changedDateFrom,
                            date_to: changedDateTo,
                        })
                    }}
                    dateOptions={[
                        { key: 'Custom', values: [] },
                        { key: 'Last 24 hours', values: ['-24h'] },
                        { key: 'Last 7 days', values: ['-7d'] },
                        { key: 'Last 21 days', values: ['-21d'] },
                    ]}
                    dropdownPlacement="bottom-end"
                />
                <DurationFilter
                    onChange={(newFilter) => {
                        setFilters({ session_recording_duration: newFilter })
                    }}
                    initialFilter={filters.session_recording_duration as RecordingDurationFilter}
                    pageKey={'session-recordings'}
                />
            </div>

            <LemonLabel info="Show recordings where all of the events or actions listed below happen.">
                Filter by events and actions
            </LemonLabel>

            <ActionFilter
                filters={localFilters}
                setFilters={(payload) => {
                    // reportRecordingsListFilterAdded(SessionRecordingFilterType.EventAndAction)
                    setLocalFilters(payload)
                }}
                typeKey={'session-recordings-2'}
                mathAvailability={MathAvailability.None}
                buttonCopy="Filter for events or actions"
                hideRename
                hideDuplicate
                showNestedArrow={false}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Actions, TaxonomicFilterGroupType.Events]}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
                propertyFiltersPopover
            />

            <LemonLabel info="Show recordings by persons who match the set criteria">
                Filter by persons and cohorts
            </LemonLabel>

            <PropertyFilters
                pageKey={'session-recordings'}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
                propertyFilters={filters.properties}
                onChange={(properties) => {
                    setFilters({ properties })
                }}
            />

            {/* <div className="border rounded p-4 bg-light">
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
                            TaxonomicFilterGroupType.HogQLExpression,
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
            </div> */}
        </div>
    )
}
