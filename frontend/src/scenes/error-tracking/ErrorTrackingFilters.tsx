import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dateMapping } from 'lib/utils'
import { useEffect, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { errorTrackingLogic } from './errorTrackingLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => dm.key != 'Yesterday')

export const ErrorTrackingFilters = (): JSX.Element => {
    return (
        <div className="space-y-1">
            <div className="flex gap-2 items-center">
                <DateRange />
                <FilterGroup />
                <UniversalSearch />
                <InternalAccounts />
            </div>
        </div>
    )
}

const FilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(errorTrackingLogic)
    const { setFilterGroup } = useActions(errorTrackingLogic)

    return (
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

const DateRange = (): JSX.Element => {
    const { dateRange } = useValues(errorTrackingLogic)
    const { setDateRange } = useActions(errorTrackingLogic)

    return (
        <DateFilter
            size="small"
            dateFrom={dateRange.date_from}
            dateTo={dateRange.date_to}
            dateOptions={errorTrackingDateOptions}
            onChange={(changedDateFrom, changedDateTo) =>
                setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
            }
        />
    )
}

const UniversalSearch = (): JSX.Element => {
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

const InternalAccounts = (): JSX.Element => {
    const { filterTestAccounts } = useValues(errorTrackingLogic)
    const { setFilterTestAccounts } = useActions(errorTrackingLogic)

    return (
        <div>
            <TestAccountFilter
                size="small"
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts || false)}
            />
        </div>
    )
}
