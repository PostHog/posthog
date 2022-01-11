import React, { CSSProperties, useEffect, useMemo } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { objectsEqual } from 'lib/utils'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    pageKey?: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    style?: CSSProperties
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
    greyBadges?: boolean
    eventNames?: string[]
}

let uniqueMemoizedIndex = 0

export function PropertyFilters({
    propertyFilters,
    onChange,
    pageKey: pageKeyInput,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    taxonomicGroupTypes,
    style = {},
    showNestedArrow = false,
    greyBadges = false,
    eventNames = [],
}: PropertyFiltersProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${uniqueMemoizedIndex++}`, [pageKeyInput])
    const propertyFilterLogicProps = { propertyFilters, onChange, pageKey }
    const logic = propertyFilterLogic(propertyFilterLogicProps)
    const { filterWithEmpty, filters } = useValues(logic)
    const { remove, setFilters } = useActions(logic)
    useEffect(() => {
        if (!objectsEqual(propertyFilters ?? [], filters ?? [])) {
            setFilters(propertyFilters ?? [])
        }
    }, [propertyFilters])

    return (
        <div className="property-filters" style={style}>
            <BindLogic logic={propertyFilterLogic} props={propertyFilterLogicProps}>
                {filterWithEmpty.map((item, index) => {
                    return (
                        <FilterRow
                            key={index}
                            item={item}
                            index={index}
                            totalCount={filterWithEmpty.length - 1} // empty state
                            filters={filterWithEmpty}
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
                                    propertyFilterLogicProps={propertyFilterLogicProps}
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
