import React from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { DurationFilter } from './DurationFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { IconFilter } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsFilters({
    personUUID,
    isPersonPage = false,
}: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const { entityFilters, propertyFilters, fromDate, toDate, durationFilter, showFilters } = useValues(
        sessionRecordingsTableLogicInstance
    )
    const {
        setEntityFilters,
        setPropertyFilters,
        setDateRange,
        setDurationFilter,
        enableFilter,
        reportRecordingsListFilterAdded,
    } = useActions(sessionRecordingsTableLogicInstance)

    return (
        <div className="flex flex-wrap items-end justify-between gap-4 mb-4">
            {showFilters ? (
                // eslint-disable-next-line react/forbid-dom-props
                <div className="flex-1 border rounded p-4" style={{ minWidth: '400px', maxWidth: '700px' }}>
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
                        />
                    </div>
                    {!isPersonPage && (
                        <div className="mt-8 space-y-2">
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
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconFilter />}
                    onClick={() => {
                        enableFilter()
                        if (isPersonPage) {
                            const entityFilterButtons = document.querySelectorAll('.entity-filter-row button')
                            if (entityFilterButtons.length > 0) {
                                ;(entityFilterButtons[0] as HTMLElement).click()
                            }
                        }
                    }}
                >
                    Filter recordings
                </LemonButton>
            )}

            <div className="flex items-center gap-4">
                <DateFilter
                    dateFrom={fromDate ?? '-7d'}
                    dateTo={toDate ?? undefined}
                    onChange={(changedDateFrom, changedDateTo) => {
                        reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
                        setDateRange(changedDateFrom, changedDateTo ?? undefined)
                    }}
                    dateOptions={[
                        { key: 'Custom', values: [] },
                        { key: 'Last 24 hours', values: ['-24h'] },
                        { key: 'Last 7 days', values: ['-7d'] },
                        { key: 'Last 21 days', values: ['-21d'] },
                    ]}
                />
                <div className="flex gap-2">
                    <LemonLabel>Duration</LemonLabel>
                    <DurationFilter
                        onChange={(newFilter) => {
                            reportRecordingsListFilterAdded(SessionRecordingFilterType.Duration)
                            setDurationFilter(newFilter)
                        }}
                        initialFilter={durationFilter}
                        pageKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                    />
                </div>
            </div>
        </div>
    )
}
