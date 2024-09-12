import { LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters, { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { RecordingUniversalFilters } from '~/types'

import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'
import { DurationFilter } from './DurationFilter'

export const RecordingsUniversalFilters = ({
    filters,
    setFilters,
    className,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    className?: string
}): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)

    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)
    const { setOrderBy } = useActions(sessionRecordingsPlaylistLogic)

    const durationFilter = filters.duration[0]

    return (
        <div className={clsx('divide-y bg-bg-light rounded', className)}>
            <div className="flex justify-between px-2 py-1.5 flex-wrap gap-1">
                <div className="flex flex-wrap gap-2 items-center">
                    <div className="flex items-center">
                        <AndOrFilterSelect
                            value={filters.filter_group.type}
                            onChange={(type) => {
                                let values = filters.filter_group.values

                                // set the type on the nested child when only using a single filter group
                                const hasSingleGroup = values.length === 1
                                if (hasSingleGroup) {
                                    const group = values[0] as UniversalFiltersGroup
                                    values = [{ ...group, type }]
                                }

                                setFilters({
                                    filter_group: {
                                        type: type,
                                        values: values,
                                    },
                                })
                            }}
                            topLevelFilter={true}
                            suffix={['filter', 'filters']}
                        />
                    </div>
                    <DateFilter
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
                        size="small"
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
                    />
                    <span className="font-medium">sorted by</span>
                    <LemonSelect
                        options={[
                            {
                                value: 'start_time',
                                label: 'Latest',
                            },
                            {
                                label: 'Longest',
                                options: [
                                    {
                                        value: 'duration',
                                        label: 'Total duration',
                                    },
                                    {
                                        value: 'active_seconds',
                                        label: 'Active duration',
                                    },
                                    {
                                        value: 'inactive_seconds',
                                        label: 'Inactive duration',
                                    },
                                ],
                            },
                            {
                                label: 'Most active',
                                options: [
                                    {
                                        value: 'click_count',
                                        label: 'Clicks',
                                    },
                                    {
                                        value: 'keypress_count',
                                        label: 'Key presses',
                                    },
                                    {
                                        value: 'mouse_activity_count',
                                        label: 'Mouse activity',
                                    },
                                ],
                            },
                            {
                                value: 'console_error_count',
                                label: 'Most errors',
                            },
                        ]}
                        size="small"
                        value={orderBy}
                        onChange={setOrderBy}
                    />
                </div>
                <div>
                    <TestAccountFilter
                        size="small"
                        filters={filters}
                        onChange={(testFilters) =>
                            setFilters({ filter_test_accounts: testFilters.filter_test_accounts })
                        }
                    />
                </div>
            </div>
            <div className="flex gap-2 p-2">
                <UniversalFilters
                    rootKey="session-recordings"
                    group={filters.filter_group}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.Replay,
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.SessionProperties,
                    ]}
                    onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                >
                    <RecordingsUniversalFilterGroup />
                </UniversalFilters>
            </div>
        </div>
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
                        <UniversalFilters.AddFilterButton size="small" type="secondary" />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={allowInitiallyOpen}
                    />
                )
            })}
        </>
    )
}
