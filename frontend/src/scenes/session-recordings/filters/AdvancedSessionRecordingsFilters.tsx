import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { EntityTypes, FilterType, FilterableLogLevel, RecordingDurationFilter, RecordingFilters } from '~/types'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationFilter } from './DurationFilter'
import { LemonButtonWithDropdown, LemonCheckbox } from '@posthog/lemon-ui'

export const AdvancedSessionRecordingsFilters = ({
    filters,
    setFilters,
    localFilters,
    setLocalFilters,
    showPropertyFilters,
    usesListingV3,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    localFilters: FilterType
    setLocalFilters: (localFilters: FilterType) => void
    showPropertyFilters?: boolean
    usesListingV3?: boolean
}): JSX.Element => {
    return (
        <div>
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
                    dropdownPlacement="bottom-start"
                />
                <DurationFilter
                    onChange={(newRecordingDurationFilter, newDurationType) => {
                        setFilters({
                            session_recording_duration: newRecordingDurationFilter,
                            duration_type_filter: newDurationType,
                        })
                    }}
                    recordingDurationFilter={filters.session_recording_duration as RecordingDurationFilter}
                    durationTypeFilter={filters.duration_type_filter || 'duration'}
                    usesListingV3={usesListingV3}
                    pageKey={'session-recordings'}
                />
            </div>

            <LemonLabel info="Show recordings where all of the events or actions listed below happen.">
                Filter by events and actions
            </LemonLabel>

            <ActionFilter
                filters={localFilters}
                setFilters={(payload) => {
                    setLocalFilters(payload)
                }}
                typeKey={'session-recordings'}
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
                addFilterDefaultOptions={{
                    id: '$pageview',
                    name: '$pageview',
                    type: EntityTypes.EVENTS,
                }}
            />

            {showPropertyFilters && (
                <>
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
                            setFilters({ properties })
                        }}
                    />
                </>
            )}

            <LemonLabel info="Show recordings that have captured console log messages">
                Filter by console logs
            </LemonLabel>
            <ConsoleFilters
                filters={filters}
                setConsoleFilters={(x) =>
                    setFilters({
                        console_logs: x,
                    })
                }
            />
        </div>
    )
}

function ConsoleFilters({
    filters,
    setConsoleFilters,
}: {
    filters: RecordingFilters
    setConsoleFilters: (selection: FilterableLogLevel[]) => void
}): JSX.Element {
    function updateChoice(checked: boolean, level: FilterableLogLevel): void {
        const newChoice = filters.console_logs?.filter((c) => c !== level) || []
        if (checked) {
            setConsoleFilters([...newChoice, level])
        } else {
            setConsoleFilters(newChoice)
        }
    }

    return (
        <LemonButtonWithDropdown
            status="stealth"
            type="secondary"
            data-attr={'console-filters'}
            dropdown={{
                sameWidth: true,
                closeOnClickInside: false,
                overlay: [
                    <>
                        <LemonCheckbox
                            size="small"
                            fullWidth
                            checked={!!filters.console_logs?.includes('log')}
                            onChange={(checked) => {
                                updateChoice(checked, 'log')
                            }}
                            label={'log'}
                        />
                        <LemonCheckbox
                            size="small"
                            fullWidth
                            checked={!!filters.console_logs?.includes('warn')}
                            onChange={(checked) => updateChoice(checked, 'warn')}
                            label={'warn'}
                        />
                        <LemonCheckbox
                            size="small"
                            fullWidth
                            checked={!!filters.console_logs?.includes('error')}
                            onChange={(checked) => updateChoice(checked, 'error')}
                            label={'error'}
                        />
                    </>,
                ],
                actionable: true,
            }}
        >
            {filters.console_logs?.map((x) => `console.${x}`).join(' or ') || (
                <span className={'text-muted'}>Console types to filter for...</span>
            )}
        </LemonButtonWithDropdown>
    )
}
