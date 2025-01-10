import { IconFilter, IconPeopleFilled } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SettingsMenu, SettingsToggle } from 'lib/components/PanelLayout/PanelLayout'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
import { SettingsBar } from 'scenes/session-recordings/components/PanelSettings'
import { DurationFilter } from 'scenes/session-recordings/filters/DurationFilter'

import { NodeKind } from '~/queries/schema'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { sessionRecordingsPlaylistLogic } from '../sessionRecordingsPlaylistLogic'

export const FiltersPanel = (): JSX.Element => {
    const { filters } = useValues(sessionRecordingsPlaylistLogic({ updateSearchParams: true }))
    const { setFilters } = useActions(sessionRecordingsPlaylistLogic({ updateSearchParams: true }))

    const featureFlags = useValues(featureFlagLogic)
    const allowReplayHogQLFilters = !!featureFlags[FEATURE_FLAGS.REPLAY_HOGQL_FILTERS]
    const allowReplayFlagsFilters = !!featureFlags[FEATURE_FLAGS.REPLAY_FLAGS_FILTERS]

    const durationFilter = filters.duration[0]

    const taxonomicGroupTypes = [
        TaxonomicFilterGroupType.Replay,
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.SessionProperties,
    ]

    if (allowReplayHogQLFilters) {
        taxonomicGroupTypes.push(TaxonomicFilterGroupType.HogQLExpression)
    }
    if (allowReplayFlagsFilters) {
        taxonomicGroupTypes.push(TaxonomicFilterGroupType.EventFeatureFlags)
    }

    return (
        <>
            <div className="p-2 space-y-1 bg-bg-light">
                <DateFilter
                    size="xsmall"
                    type="tertiary"
                    dateFrom={filters.date_from ?? '-3d'}
                    dateTo={filters.date_to}
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
                            duration: [{ ...newRecordingDurationFilter, key: newDurationType }],
                        })
                    }}
                    recordingDurationFilter={durationFilter}
                    durationTypeFilter={durationFilter.key}
                    pageKey="session-recordings"
                    size="xsmall"
                    type="tertiary"
                />
                <UniversalFilters
                    rootKey="session-recordings"
                    group={filters.filter_group}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                    onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                >
                    <RecordingsUniversalFilterGroup />
                </UniversalFilters>
            </div>
            <BottomSettings />
        </>
    )
}

const RecordingsUniversalFilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState(false)

    useEffect(() => {
        setAllowInitiallyOpen(true)
    }, [])

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <RecordingsUniversalFilterGroup />
                        <UniversalFilters.AddFilterButton size="xsmall" />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={allowInitiallyOpen}
                        metadataSource={{ kind: NodeKind.RecordingsQuery }}
                    />
                )
            })}
        </>
    )
}

function BottomSettings(): JSX.Element {
    const { filters } = useValues(sessionRecordingsPlaylistLogic)
    const { setFilters } = useActions(sessionRecordingsPlaylistLogic)

    const onChangeOperator = (type: FilterLogicalOperator): void => {
        let values = filters.filter_group.values

        // set the type on the nested child when only using a single filter group
        const hasSingleGroup = values.length === 1
        if (hasSingleGroup) {
            const group = values[0] as UniversalFiltersGroup
            values = [{ ...group, type }]
        }

        setFilters({ filter_group: { type: type, values: values } })
    }

    return (
        <SettingsBar border="top">
            <SettingsMenu
                highlightWhenActive={false}
                items={[
                    {
                        label: 'Any',
                        onClick: () => onChangeOperator(FilterLogicalOperator.Or),
                        active: filters.filter_group.type === FilterLogicalOperator.Or,
                    },
                    {
                        label: 'All',
                        onClick: () => onChangeOperator(FilterLogicalOperator.And),
                        active: filters.filter_group.type === FilterLogicalOperator.And,
                    },
                ]}
                icon={<IconFilter />}
                label={`Match ${filters.filter_group.type === FilterLogicalOperator.And ? 'all' : 'any'}...`}
            />
            <SettingsToggle
                title="Show internal users"
                icon={<IconPeopleFilled />}
                label="Show internal users"
                active={filters.filter_test_accounts || false}
                onClick={() => setFilters({ filter_test_accounts: !filters.filter_test_accounts })}
            />
        </SettingsBar>
    )
}
