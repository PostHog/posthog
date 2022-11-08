import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { RecordingFilters } from '~/types'

interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
}

export function SessionRecordingsFilters({
    filters,
    setFilters,
    showPropertyFilters,
}: SessionRecordingsFiltersProps): JSX.Element {
    return (
        <>
            <div className="flex-1 border rounded p-4">
                <div className="space-y-2">
                    <LemonLabel info="Show recordings where all of the events or actions listed below happen.">
                        Filter by events and actions
                    </LemonLabel>
                    <ActionFilter
                        bordered
                        filters={{
                            actions: filters.actions,
                            events: filters.events,
                        }}
                        setFilters={(payload) => {
                            // reportRecordingsListFilterAdded(SessionRecordingFilterType.EventAndAction)
                            setFilters({
                                events: payload.events,
                                actions: payload.actions,
                            })
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
