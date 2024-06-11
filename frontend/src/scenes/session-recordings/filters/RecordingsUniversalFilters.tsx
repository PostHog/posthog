import { useActions, useMountedLogic, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { actionsModel } from '~/models/actionsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'

import { sessionRecordingsPlaylistLogic } from '../playlist/sessionRecordingsPlaylistLogic'
import { DurationFilter } from './DurationFilter'

export const RecordingsUniversalFilters = (): JSX.Element => {
    useMountedLogic(cohortsModel)
    useMountedLogic(actionsModel)
    const { universalFilters } = useValues(sessionRecordingsPlaylistLogic)
    const { setUniversalFilters } = useActions(sessionRecordingsPlaylistLogic)

    const durationFilter = universalFilters.duration[0]

    return (
        <div className="divide-y bg-bg-light rounded border">
            <div className="flex justify-between px-2 py-1.5">
                <div className="flex space-x-2">
                    <DateFilter
                        dateFrom={universalFilters.date_from ?? '-3d'}
                        dateTo={universalFilters.date_to}
                        disabled={universalFilters.live_mode}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setUniversalFilters({
                                ...universalFilters,
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
                            setUniversalFilters({
                                duration: [{ ...newRecordingDurationFilter, key: newDurationType }],
                            })
                        }}
                        recordingDurationFilter={durationFilter}
                        durationTypeFilter={durationFilter.key}
                        pageKey="session-recordings"
                    />
                    <TestAccountFilter
                        filters={universalFilters}
                        onChange={(testFilters) =>
                            setUniversalFilters({
                                ...universalFilters,
                                filter_test_accounts: testFilters.filter_test_accounts,
                            })
                        }
                    />
                </div>
                <div>
                    <AndOrFilterSelect
                        value={universalFilters.filter_group.type}
                        onChange={(type) => {
                            setUniversalFilters({
                                ...universalFilters,
                                filter_group: {
                                    type: type,
                                    values: universalFilters.filter_group.values,
                                },
                            })
                        }}
                        disabledReason="'Or' filtering is not supported yet"
                        topLevelFilter={true}
                        suffix={['filter', 'filters']}
                    />
                </div>
            </div>
            <div className="flex gap-2 p-2">
                <UniversalFilters
                    rootKey="session-recordings"
                    group={universalFilters.filter_group}
                    taxonomicEntityFilterGroupTypes={[
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                    ]}
                    taxonomicPropertyFilterGroupTypes={[
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.SessionProperties,
                    ]}
                    onChange={(filterGroup) => {
                        setUniversalFilters({
                            ...universalFilters,
                            filter_group: filterGroup,
                        })
                    }}
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

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <RecordingsUniversalFilterGroup />
                        <UniversalFilters.AddFilterButton />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                    />
                )
            })}
        </>
    )
}
