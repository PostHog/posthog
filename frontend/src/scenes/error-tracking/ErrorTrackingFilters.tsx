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
    const { setSearchQuery } = useActions(errorTrackingLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)

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
        autoSelectItem: false,
    }

    const onClose = (value?: string): void => {
        searchInputRef.current?.blur()
        setSearchQuery(value ?? '')
        setVisible(false)
    }

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <InfiniteSelectResults
                        focusInput={() => searchInputRef.current?.focus()}
                        taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                        popupAnchorElement={floatingRef.current}
                        useVerticalLayout={true}
                    />
                }
                matchWidth
                visible={visible}
                closeOnClickInside={false}
                floatingRef={floatingRef}
                onClickOutside={() => onClose()}
            >
                <TaxonomicFilterSearchInput
                    prefix={<RecordingsUniversalFilterGroup />}
                    onEnter={onClose}
                    onClick={() => setVisible(true)}
                    searchInputRef={searchInputRef}
                    onClose={onClose}
                    size="small"
                    fullWidth
                />
            </LemonDropdown>
        </BindLogic>
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
