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
import { cn } from 'lib/utils/css-classes'
import { ReactNode, useEffect, useRef, useState } from 'react'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { errorTrackingLogic } from './errorTrackingLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => dm.key != 'Yesterday')

const taxonomicFilterLogicKey = 'error-tracking'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

export const ErrorTrackingFilters = ({ children }: { children: ReactNode }): JSX.Element => {
    return (
        <div className="space-y-1">
            <div className="flex gap-2 items-center">{children}</div>
        </div>
    )
}

export const FilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(errorTrackingLogic)
    const { setFilterGroup } = useActions(errorTrackingLogic)

    return (
        <UniversalFilters
            rootKey={taxonomicFilterLogicKey}
            group={filterGroup.values[0] as UniversalFiltersGroup}
            // TODO: Probably makes sense to create a new taxonomic group for exception-specific event property filters only, keep it clean.
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
        >
            <UniversalSearch />
        </UniversalFilters>
    )
}

const UniversalSearch = (): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { searchQuery } = useValues(errorTrackingLogic)
    const { setSearchQuery } = useActions(errorTrackingLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)

    const onClose = (query: string): void => {
        searchInputRef.current?.blur()
        setVisible(false)
        setSearchQuery(query)
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey,
        taxonomicGroupTypes,
        onChange: (taxonomicGroup, value, item, originalQuery) => {
            searchInputRef.current?.blur()
            setVisible(false)
            addGroupFilter(taxonomicGroup, value, item, originalQuery)
        },
        onEnter: onClose,
        autoSelectItem: false,
        initialSearchQuery: searchQuery,
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
                onClickOutside={() => onClose('')}
            >
                <TaxonomicFilterSearchInput
                    prefix={<RecordingsUniversalFilterGroup />}
                    onClick={() => setVisible(true)}
                    searchInputRef={searchInputRef}
                    onClose={() => onClose('')}
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
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <UniversalSearch />
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

export const DateRangeFilter = ({
    className,
    fullWidth = false,
    size = 'small',
}: {
    className?: string
    fullWidth?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}): JSX.Element => {
    const { dateRange } = useValues(errorTrackingLogic)
    const { setDateRange } = useActions(errorTrackingLogic)
    return (
        <span className={cn('rounded bg-surface-primary', className)}>
            <DateFilter
                size={size}
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                fullWidth={fullWidth}
                dateOptions={errorTrackingDateOptions}
                onChange={(changedDateFrom, changedDateTo) =>
                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                }
            />
        </span>
    )
}

export const InternalAccountsFilter = (): JSX.Element => {
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
