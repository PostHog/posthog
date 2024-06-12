import { LemonButtonWithDropdown, LemonCheckbox, LemonInput } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { groupsModel } from '~/models/groupsModel'
import { EntityTypes, FilterableLogLevel, RecordingFilters } from '~/types'

import { DurationFilter } from './DurationFilter'

function DateAndDurationFilters({
    filters,
    setFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Time and duration</LemonLabel>
            <div className="flex flex-row flex-wrap gap-2">
                <DateFilter
                    dateFrom={filters.date_from ?? '-3d'}
                    dateTo={filters.date_to}
                    disabled={filters.live_mode}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setFilters({
                            date_from: changedDateFrom,
                            date_to: changedDateTo,
                        })
                    }}
                    dateOptions={[
                        { key: 'Custom', values: [] },
                        { key: 'Last 24 hours', values: ['-24h'] },
                        { key: 'Last 3 days', values: ['-3d'] },
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
                    recordingDurationFilter={filters.session_recording_duration || defaultRecordingDurationFilter}
                    durationTypeFilter={filters.duration_type_filter || 'duration'}
                    pageKey="session-recordings"
                />
            </div>
        </div>
    )
}

export const AdvancedSessionRecordingsFilters = ({
    filters,
    setFilters,
    showPropertyFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    showPropertyFilters?: boolean
}): JSX.Element => {
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const { featureFlags } = useValues(featureFlagLogic)

    const allowedPropertyTaxonomyTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.HogQLExpression,
        ...groupsTaxonomicTypes,
    ]

    const hasHogQLFiltering = featureFlags[FEATURE_FLAGS.SESSION_REPLAY_HOG_QL_FILTERING]

    if (hasHogQLFiltering) {
        allowedPropertyTaxonomyTypes.push(TaxonomicFilterGroupType.SessionProperties)
    }

    const addFilterTaxonomyTypes = [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]
    if (hasHogQLFiltering) {
        addFilterTaxonomyTypes.push(TaxonomicFilterGroupType.SessionProperties)
    }

    return (
        <div className="space-y-2 bg-light p-3">
            <LemonLabel info="Show recordings where all of the events or actions listed below happen.">
                Events and actions
            </LemonLabel>

            <ActionFilter
                filters={{ events: filters.events || [], actions: filters.actions || [] }}
                setFilters={(payload) => {
                    setFilters({
                        events: payload.events || [],
                        actions: payload.actions || [],
                    })
                }}
                typeKey="session-recordings"
                mathAvailability={MathAvailability.None}
                hideRename
                hideDuplicate
                showNestedArrow={false}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Actions, TaxonomicFilterGroupType.Events]}
                propertiesTaxonomicGroupTypes={allowedPropertyTaxonomyTypes}
                propertyFiltersPopover
                addFilterDefaultOptions={{
                    id: '$pageview',
                    name: '$pageview',
                    type: EntityTypes.EVENTS,
                }}
                buttonProps={{ type: 'secondary', size: 'small' }}
            />

            {hasHogQLFiltering ? (
                <LemonLabel info="Show recordings by persons, cohorts, and more that match the set criteria">
                    Properties
                </LemonLabel>
            ) : (
                <LemonLabel info="Show recordings by persons who match the set criteria">
                    Persons and cohorts
                </LemonLabel>
            )}

            <TestAccountFilterSwitch
                checked={filters.filter_test_accounts ?? false}
                onChange={(val) => setFilters({ filter_test_accounts: val })}
                fullWidth
            />

            {showPropertyFilters && (
                <PropertyFilters
                    pageKey="session-recordings"
                    buttonText={hasHogQLFiltering ? 'Add filter' : 'Person or cohort'}
                    taxonomicGroupTypes={addFilterTaxonomyTypes}
                    propertyFilters={filters.properties}
                    onChange={(properties) => {
                        setFilters({ properties })
                    }}
                />
            )}

            <DateAndDurationFilters filters={filters} setFilters={setFilters} />

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
            <LemonLabel>Console logs</LemonLabel>
            <div className="flex flex-row space-x-2">
                <LemonInput
                    className="grow"
                    placeholder="containing text"
                    value={filters.console_search_query}
                    onChange={(s: string): void => {
                        setFilters({
                            console_search_query: s,
                        })
                    }}
                />
            </div>
            <LemonButtonWithDropdown
                type="secondary"
                data-attr="console-filters"
                fullWidth={true}
                dropdown={{
                    matchWidth: true,
                    closeOnClickInside: false,
                    overlay: [
                        <>
                            <LemonCheckbox
                                size="small"
                                fullWidth
                                checked={!!filters.console_logs?.includes('info')}
                                onChange={(checked) => {
                                    updateLevelChoice(checked, 'info')
                                }}
                                label="info"
                            />
                            <LemonCheckbox
                                size="small"
                                fullWidth
                                checked={!!filters.console_logs?.includes('warn')}
                                onChange={(checked) => updateLevelChoice(checked, 'warn')}
                                label="warn"
                            />
                            <LemonCheckbox
                                size="small"
                                fullWidth
                                checked={!!filters.console_logs?.includes('error')}
                                onChange={(checked) => updateLevelChoice(checked, 'error')}
                                label="error"
                            />
                        </>,
                    ],
                    actionable: true,
                }}
            >
                {filters.console_logs?.map((x) => `console.${x}`).join(' or ') || (
                    <span className="text-muted">Console types to filter for...</span>
                )}
            </LemonButtonWithDropdown>
        </>
    )
}
