import { LemonDropdown } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dateMapping } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { errorTrackingLogic } from './errorTrackingLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => dm.key != 'Yesterday')

export const ErrorTrackingFilters = (): JSX.Element => {
    return (
        <div className="space-y-1">
            <div className="flex gap-2 items-center">
                <DateRange />
                <FilterGroup />
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
                TaxonomicFilterGroupType.HogQLExpression,
            ]}
            onChange={setFilterGroup}
        >
            <UniversalSearch />
        </UniversalFilters>
    )
}

const UniversalSearch = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: 'error-tracking',
        taxonomicGroupTypes: [
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.Cohorts,
            TaxonomicFilterGroupType.HogQLExpression,
        ],
        onChange: (taxonomicGroup, value, item, originalQuery) => {
            addGroupFilter(taxonomicGroup, value, item, originalQuery)
            setVisible(false)
        },
    }

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const focusInput = (): void => searchInputRef.current?.focus()

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <InfiniteSelectResults
                        focusInput={focusInput}
                        taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                        popupAnchorElement={searchInputRef.current}
                    />
                }
                matchWidth
                visible={visible}
                onClickInside={() => console.log('Clicked inside')}
                onClickOutside={() => setVisible(false)}
                closeOnClickInside={false}
                // referenceRef={inputRef}
                // // visible={visible}
                // placement="right-start"
                // fallbackPlacements={['left-end', 'bottom']}
                // onClickOutside={() => setVisible(false)}
            >
                <UniversalSearchInput searchInputRef={searchInputRef} setVisible={setVisible} />
            </LemonDropdown>
        </BindLogic>
    )
}

const UniversalSearchInput = ({
    searchInputRef,
    setVisible,
}: {
    searchInputRef: any
    setVisible: any
}): JSX.Element => {
    const { searchQuery } = useValues(errorTrackingLogic)
    const { setSearchQuery: setErrorTrackingSearchQuery } = useActions(errorTrackingLogic)
    const { setSearchQuery: setTaxonomicFilterSearchQuery } = useActions(taxonomicFilterLogic)

    return (
        <TaxonomicFilterSearchInput
            value={searchQuery}
            onChange={(value) => {
                setErrorTrackingSearchQuery(value)
                setTaxonomicFilterSearchQuery(value)
            }}
            searchInputRef={searchInputRef}
            onClose={() => setVisible(false)}
            size="small"
            onClick={() => setVisible(true)}
            prefix={<RecordingsUniversalFilterGroup />}
            onPressEnter={() => setVisible(false)}
            fullWidth
        />
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
