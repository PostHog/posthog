import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import {
    EntityTypes,
    FilterableLogLevel,
    FilterType,
    LocalRecordingFilters,
    RecordingDurationFilter,
    RecordingFilters,
} from '~/types'
import { useEffect, useState } from 'react'
import equal from 'fast-deep-equal'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationFilter } from './DurationFilter'
import { LemonButton, LemonButtonWithDropdown, LemonCheckbox, LemonDivider } from '@posthog/lemon-ui'
import { DurationTypeSelect } from 'scenes/session-recordings/filters/DurationTypeSelect'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { useActions, useValues } from 'kea'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

interface SessionRecordingsFiltersProps {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
    onReset?: () => void
    usesListingV3?: boolean
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

export function SessionRecordingsFilters({
    filters,
    setFilters,
    showPropertyFilters,
    onReset,
    usesListingV3,
}: SessionRecordingsFiltersProps): JSX.Element {
    const [localFilters, setLocalFilters] = useState<FilterType>(filtersToLocalFilters(filters))

    const { durationTypeToShow } = useValues(playerSettingsLogic)
    const { setDurationTypeToShow } = useActions(playerSettingsLogic)

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

            <FlaggedFeature flag={FEATURE_FLAGS.SESSION_RECORDING_TEST_ACCOUNTS_FILTER} match={true}>
                <div className={'pt-2'}>
                    <TestAccountFilter
                        filters={filters}
                        onChange={(testFilters) =>
                            setFilters({ filter_test_accounts: testFilters.filter_test_accounts })
                        }
                    />
                </div>
            </FlaggedFeature>

            <div className={'flex flex-col py-1 px-2 '}>
                <LemonDivider />

                <div className={'flex flex-row items-center justify-end space-x-2'}>
                    <span>Show</span>
                    <DurationTypeSelect
                        value={durationTypeToShow}
                        onChange={(value) => setDurationTypeToShow(value)}
                        onChangeEventDescription={'session recording list duration type to show selected'}
                    />
                </div>
            </div>
        </div>
    )
}
