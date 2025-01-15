/**
 * @fileoverview Filters panel for session recordings playlist.
 */
import { IconFilter, IconPeopleFilled } from '@posthog/icons'
import { LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SettingsMenu } from 'lib/components/PanelLayout/PanelLayout'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useState } from 'react'
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

    /** For the internal users filter */
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
            <div className="px-2 space-y-1 bg-bg-light border-b py-2 Playlist__filters">
                <div className="flex items-center justify-between">
                    <h3 className="px-2 truncate" title="Filters">
                        Filters
                    </h3>
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
                </div>
                <div className="mx-2">
                    {/* This divider has to be within a div, because otherwise horizontal margin ADDS to the width */}
                    <LemonDivider className="my-0" />
                </div>
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
                <LemonSwitch
                    checked={filters.filter_test_accounts || false}
                    onChange={() => setFilters({ filter_test_accounts: !filters.filter_test_accounts })}
                    size="small"
                    className="ml-1 py-1"
                    label={
                        <div className="flex text-xs gap-2">
                            <IconPeopleFilled />
                            <span>Show internal users</span>
                        </div>
                    }
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
                        <UniversalFilters.AddFilterButton size="xsmall" type="primary" />
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
