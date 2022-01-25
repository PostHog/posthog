import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter, PropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { FilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: PropertyFilter[]) => void
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    style?: CSSProperties
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
    greyBadges?: boolean
    eventNames?: string[]
    /**
     * Pinned filters are not included in property filtering
     * The component setting them is responsible for ensuring the pinned filter is applied
     **/
    pinnedFilters?: (string | JSX.Element)[]
}

export function PropertyFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    taxonomicGroupTypes,
    style = {},
    showNestedArrow = false,
    greyBadges = false,
    eventNames = [],
    pinnedFilters = [],
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters } = useActions(propertyFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    return (
        <div className="property-filters" style={style}>
            {pinnedFilters?.map((pinnedFilter, index) => {
                return (
                    <FilterButton key={index} onClick={() => {}} greyBadges={true} pinned={true}>
                        {pinnedFilter}
                    </FilterButton>
                )
            })}
            <BindLogic logic={propertyFilterLogic} props={logicProps}>
                {filtersWithNew.map((item, index) => {
                    return (
                        <FilterRow
                            key={index}
                            item={item}
                            index={index}
                            totalCount={filtersWithNew.length - 1} // empty state
                            filters={filtersWithNew}
                            pageKey={pageKey}
                            showConditionBadge={showConditionBadge}
                            disablePopover={disablePopover}
                            popoverPlacement={popoverPlacement}
                            taxonomicPopoverPlacement={taxonomicPopoverPlacement}
                            showNestedArrow={showNestedArrow}
                            label={'Add filter'}
                            onRemove={remove}
                            greyBadges={greyBadges}
                            filterComponent={(onComplete) => (
                                <TaxonomicPropertyFilter
                                    key={index}
                                    pageKey={pageKey}
                                    index={index}
                                    onComplete={onComplete}
                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                    eventNames={eventNames}
                                    disablePopover={disablePopover}
                                    selectProps={{
                                        delayBeforeAutoOpen: 150,
                                        placement: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                    }}
                                />
                            )}
                        />
                    )
                })}
            </BindLogic>
        </div>
    )
}
