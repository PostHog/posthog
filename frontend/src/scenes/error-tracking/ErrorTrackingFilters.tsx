import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dateMapping } from 'lib/utils'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => dm.key != 'Yesterday')

export const FilterGroup = ({ children }: { children?: React.ReactNode }): JSX.Element => {
    const { filterGroup, filterTestAccounts } = useValues(errorTrackingLogic)
    const { setFilterGroup, setFilterTestAccounts } = useActions(errorTrackingLogic)

    return (
        <div className="flex flex-1 items-center justify-between space-x-2">
            <div className="flex flex-1 items-center gap-2 mx-2">
                {children}
                <UniversalFilters
                    rootKey="error-tracking"
                    group={filterGroup}
                    // TODO: Probably makes sense to create a new taxonomic group for exception-specific event property filters only, keep it clean.
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.Cohorts,
                    ]}
                    onChange={setFilterGroup}
                >
                    <RecordingsUniversalFilterGroup />
                </UniversalFilters>
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

export const Options = (): JSX.Element => {
    const { dateRange, assignee } = useValues(errorTrackingLogic)
    const { setDateRange, setAssignee } = useActions(errorTrackingLogic)
    const { orderBy } = useValues(errorTrackingSceneLogic)
    const { setOrderBy } = useActions(errorTrackingSceneLogic)

    return (
        <div className="flex justify-between">
            <div className="flex gap-4 py-2">
                <div className="flex items-center gap-1">
                    <span>Date range:</span>
                    <DateFilter
                        dateFrom={dateRange.date_from}
                        dateTo={dateRange.date_to}
                        dateOptions={errorTrackingDateOptions}
                        onChange={(changedDateFrom, changedDateTo) => {
                            setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                        }}
                        size="small"
                    />
                </div>
                <div className="flex items-center gap-1">
                    <span>Sort by:</span>
                    <LemonSelect
                        onSelect={setOrderBy}
                        onChange={setOrderBy}
                        value={orderBy}
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
                </div>
            </div>
            <div className="flex items-center gap-1">
                <>
                    <span>Assigned to:</span>
                    <MemberSelect
                        value={assignee}
                        onChange={(user) => {
                            setAssignee(user?.id || null)
                        }}
                    />
                </>
            </div>
        </div>
    )
}

export const UniversalSearch = (): JSX.Element => {
    const { searchQuery } = useValues(errorTrackingLogic)
    const { setSearchQuery } = useActions(errorTrackingLogic)

    return (
        <LemonInput
            type="search"
            placeholder="Search..."
            value={searchQuery}
            onChange={setSearchQuery}
            className="flex-grow max-w-none"
            size="small"
        />
    )
}

export default {
    FilterGroup,
    Options,
    UniversalSearch,
}
