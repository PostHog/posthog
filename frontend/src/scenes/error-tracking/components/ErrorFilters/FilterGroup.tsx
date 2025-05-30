import { LemonDropdown } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useEffect, useRef, useState } from 'react'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { errorFiltersLogic } from './errorFiltersLogic'

const taxonomicFilterLogicKey = 'error-tracking'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.ErrorTrackingIssues,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

export const FilterGroup = (): JSX.Element => {
    const { filterGroup } = useValues(errorFiltersLogic)
    const { setFilterGroup } = useActions(errorFiltersLogic)

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
    const { searchQuery } = useValues(errorFiltersLogic)
    const { setSearchQuery } = useActions(errorFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)

    const onClose = (): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey,
        taxonomicGroupTypes,
        onChange: (taxonomicGroup, value, item, originalQuery) => {
            searchInputRef.current?.blur()
            setVisible(false)
            setSearchQuery('')
            addGroupFilter(taxonomicGroup, value, item, originalQuery)
        },
        onEnter: onClose,
        autoSelectItem: false,
        initialSearchQuery: searchQuery,
        excludedProperties: { [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'] },
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
                    onClick={() => setVisible(true)}
                    searchInputRef={searchInputRef}
                    onClose={() => onClose()}
                    onChange={setSearchQuery}
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
