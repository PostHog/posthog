import React from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingsTableLogic } from '../sessionRecordingsTableLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { IconFilter, IconWithCount } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'

interface SessionRecordingsFiltersProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsFilters({
    personUUID,
    isPersonPage = false,
}: SessionRecordingsFiltersProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const { entityFilters, propertyFilters, filtersEnabled } = useValues(sessionRecordingsTableLogicInstance)

    const { setEntityFilters, setPropertyFilters, reportRecordingsListFilterAdded } = useActions(
        sessionRecordingsTableLogicInstance
    )

    return (
        <>
            {filtersEnabled ? (
                <div className="flex-1 border rounded p-4">
                    <div className="space-y-2">
                        <LemonLabel info="Show recordings where all of the events or actions listed below happen.">
                            Filter by events and actions
                        </LemonLabel>
                        <ActionFilter
                            bordered
                            filters={entityFilters}
                            setFilters={(payload) => {
                                reportRecordingsListFilterAdded(SessionRecordingFilterType.EventAndAction)
                                setEntityFilters(payload)
                            }}
                            typeKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                            mathAvailability={MathAvailability.None}
                            buttonCopy="Add filter"
                            hideRename
                            hideDuplicate
                            showNestedArrow={false}
                            actionsTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.Actions,
                                TaxonomicFilterGroupType.Events,
                            ]}
                            propertiesTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.EventFeatureFlags,
                                TaxonomicFilterGroupType.Elements,
                            ]}
                            propertyFiltersPopover
                        />
                    </div>
                    {!isPersonPage && (
                        <div className="mt-4 space-y-2">
                            <LemonLabel info="Show recordings by persons who match the set criteria">
                                Filter by persons and cohorts
                            </LemonLabel>

                            <PropertyFilters
                                pageKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
                                ]}
                                propertyFilters={propertyFilters}
                                onChange={(properties) => {
                                    reportRecordingsListFilterAdded(SessionRecordingFilterType.PersonAndCohort)
                                    setPropertyFilters(properties)
                                }}
                            />
                        </div>
                    )}
                </div>
            ) : undefined}
        </>
    )
}

export function SessionRecordingsFiltersToggle({
    personUUID,
    isPersonPage,
}: SessionRecordingsFiltersProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const { entityFilters, propertyFilters, filtersEnabled } = useValues(sessionRecordingsTableLogicInstance)
    const { setFiltersEnabled } = useActions(sessionRecordingsTableLogicInstance)

    const totalFiltersCount =
        (entityFilters.actions?.length || 0) + (entityFilters.events?.length || 0) + (propertyFilters?.length || 0)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={
                <IconWithCount count={totalFiltersCount}>
                    <IconFilter />
                </IconWithCount>
            }
            onClick={() => {
                setFiltersEnabled(!filtersEnabled)
                if (isPersonPage) {
                    const entityFilterButtons = document.querySelectorAll('.entity-filter-row button')
                    if (entityFilterButtons.length > 0) {
                        ;(entityFilterButtons[0] as HTMLElement).click()
                    }
                }
            }}
        >
            {filtersEnabled ? 'Hide filters' : 'Filter recordings'}
        </LemonButton>
    )
}
