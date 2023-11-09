import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { EntityTypes, FilterableLogLevel, FilterType, RecordingDurationFilter, RecordingFilters } from '~/types'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationFilter } from './DurationFilter'
import { LemonButtonWithDropdown, LemonCheckbox, LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { groupsModel } from '~/models/groupsModel'

export const AdvancedSessionRecordingsFilters = ({
    filters,
    setFilters,
    localFilters,
    setLocalFilters,
    showPropertyFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    localFilters: FilterType
    setLocalFilters: (localFilters: FilterType) => void
    showPropertyFilters?: boolean
}): JSX.Element => {
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="space-y-2">
            <TestAccountFilter
                filters={filters}
                onChange={(testFilters) => setFilters({ filter_test_accounts: testFilters.filter_test_accounts })}
            />

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
                        { key: 'Last 30 days', values: ['-30d'] },
                        { key: 'All time', values: ['-90d'] },
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
                    ...groupsTaxonomicTypes,
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

            <ConsoleFilters filters={filters} setFilters={setFilters} />
        </div>
    )
}

function ConsoleFilters({
    filters,
    setFilters,
}: {
    filters: RecordingFilters
    setFilters: (filterS: RecordingFilters) => void
}): JSX.Element {
    function updateLevelChoice(checked: boolean, level: FilterableLogLevel): void {
        const newChoice = filters.console_logs?.filter((c) => c !== level) || []
        if (checked) {
            setFilters({
                console_logs: [...newChoice, level],
            })
        } else {
            setFilters({
                console_logs: newChoice,
            })
        }
    }

    return (
        <>
            <LemonLabel>Filter by console logs</LemonLabel>
            <FlaggedFeature flag={FEATURE_FLAGS.CONSOLE_RECORDING_SEARCH}>
                <div className={'flex flex-row space-x-2'}>
                    <LemonInput
                        className={'grow'}
                        placeholder={'containing text'}
                        value={filters.console_search_query}
                        onChange={(s: string): void => {
                            setFilters({
                                console_search_query: s,
                            })
                        }}
                    />

                    <Tooltip
                        placement="bottom"
                        title={<>Filter recordings by console logs. Only matches recordings since October 4th.</>}
                    >
                        <LemonTag type={'highlight'}>Beta</LemonTag>
                    </Tooltip>
                </div>
            </FlaggedFeature>
            <LemonButtonWithDropdown
                status="stealth"
                type="secondary"
                data-attr={'console-filters'}
                fullWidth={true}
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
                                    updateLevelChoice(checked, 'log')
                                }}
                                label={'log'}
                            />
                            <LemonCheckbox
                                size="small"
                                fullWidth
                                checked={!!filters.console_logs?.includes('warn')}
                                onChange={(checked) => updateLevelChoice(checked, 'warn')}
                                label={'warn'}
                            />
                            <LemonCheckbox
                                size="small"
                                fullWidth
                                checked={!!filters.console_logs?.includes('error')}
                                onChange={(checked) => updateLevelChoice(checked, 'error')}
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
        </>
    )
}
