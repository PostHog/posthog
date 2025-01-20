import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { NodeKind } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters, UniversalFiltersGroup } from '~/types'

import { DurationFilter } from './DurationFilter'

export const RecordingsUniversalFilters = ({
    filters,
    setFilters,
    className,
    allowReplayHogQLFilters = false,
    allowReplayFlagsFilters = false,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    className?: string
    allowReplayFlagsFilters?: boolean
    allowReplayHogQLFilters?: boolean
}): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)

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
        <div className={clsx('divide-y bg-bg-light rounded-t', className)}>
            <div className="flex items-center justify-between px-2 py-1.5">
                <h3 className="truncate mb-0" title="Filters">
                    Filters
                </h3>
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
                        size="xsmall"
                    />
                </div>
            </div>
            <div className="flex justify-between px-2 py-1.5 flex-wrap gap-1">
                <div className="flex flex-wrap gap-2 items-center">
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
                        size="xsmall"
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
                    />
                </div>
                <div>
                    <TestAccountFilter
                        size="xsmall"
                        filters={filters}
                        onChange={(testFilters) =>
                            setFilters({ filter_test_accounts: testFilters.filter_test_accounts })
                        }
                    />
                </div>
            </div>
            <div className="flex flex-wrap gap-2 p-2">
                <UniversalFilters
                    rootKey="session-recordings"
                    group={filters.filter_group}
                    taxonomicGroupTypes={taxonomicGroupTypes}
                    onChange={(filterGroup) => setFilters({ filter_group: filterGroup })}
                >
                    <RecordingsUniversalFilterGroup size="xsmall" />
                </UniversalFilters>
            </div>
        </div>
    )
}

const RecordingsUniversalFilterGroup = ({ size = 'small' }: { size?: LemonButtonProps['size'] }): JSX.Element => {
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
                        <RecordingsUniversalFilterGroup size={size} />
                        <UniversalFilters.AddFilterButton size={size} type="secondary" />
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
