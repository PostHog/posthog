import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const ErrorTrackingFilters = ({ showOrder = true }: { showOrder?: boolean }): JSX.Element => {
    const { dateRange, filterGroup, filterTestAccounts } = useValues(errorTrackingLogic)
    const { setDateRange, setFilterGroup, setFilterTestAccounts } = useActions(errorTrackingLogic)
    const { order } = useValues(errorTrackingSceneLogic)
    const { setOrder } = useActions(errorTrackingSceneLogic)

    return (
        <div className="divide-y bg-bg-light rounded border">
            <div className="flex justify-between px-2 py-1.5 flex-wrap gap-1">
                <div className="flex flex-wrap gap-2">
                    <DateFilter
                        dateFrom={dateRange.date_from}
                        dateTo={dateRange.date_to}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                        }}
                        size="small"
                    />
                    {showOrder && (
                        <LemonSelect
                            onSelect={setOrder}
                            onChange={setOrder}
                            value={order}
                            options={[
                                {
                                    value: 'last_seen',
                                    label: 'Last seen',
                                },
                                {
                                    value: 'first_seen',
                                    label: 'First seen',
                                },
                                {
                                    value: 'occurrences',
                                    label: 'Occurrences',
                                },
                                {
                                    value: 'users',
                                    label: 'Users',
                                },
                                {
                                    value: 'sessions',
                                    label: 'Sessions',
                                },
                            ]}
                            size="small"
                        />
                    )}
                </div>
                <div>
                    <TestAccountFilter
                        size="small"
                        filters={{ filter_test_accounts: filterTestAccounts }}
                        onChange={({ filter_test_accounts }) => {
                            setFilterTestAccounts(filter_test_accounts || false)
                        }}
                    />
                </div>
            </div>
            <div className="flex flex-1 items-center space-x-2 px-2 py-1.5">
                <UniversalFilters
                    rootKey="error-tracking"
                    group={filterGroup}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts]}
                    onChange={setFilterGroup}
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
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

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
