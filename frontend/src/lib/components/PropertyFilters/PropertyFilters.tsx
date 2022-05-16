import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter, PropertyFilter, FilterLogicalOperator } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import './PropertyFilters.scss'

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
    eventNames?: string[]
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    useLemonButton?: boolean
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
    eventNames = [],
    orFiltering = false,
    propertyGroupType = null,
    useLemonButton = false,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters } = useActions(propertyFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    return (
        <div className="PropertyFilters" style={style}>
            {showNestedArrow && !disablePopover && <div className="PropertyFilters-prefix">{<>&#8627;</>}</div>}
            <div className="PropertyFilters-content">
                <BindLogic logic={propertyFilterLogic} props={logicProps}>
                    {filtersWithNew.map((item: AnyPropertyFilter, index: number) => {
                        return (
                            <FilterRow
                                key={index}
                                item={item}
                                index={index}
                                totalCount={filtersWithNew.length - 1} // empty state
                                filters={filtersWithNew}
                                pageKey={pageKey}
                                showConditionBadge={showConditionBadge}
                                disablePopover={disablePopover || orFiltering}
                                popoverPlacement={popoverPlacement}
                                taxonomicPopoverPlacement={taxonomicPopoverPlacement}
                                label={'Add filter'}
                                onRemove={remove}
                                useLemonButton={useLemonButton}
                                orFiltering={orFiltering}
                                filterComponent={(onComplete) => (
                                    <TaxonomicPropertyFilter
                                        key={index}
                                        pageKey={pageKey}
                                        index={index}
                                        onComplete={onComplete}
                                        orFiltering={orFiltering}
                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                        eventNames={eventNames}
                                        propertyGroupType={propertyGroupType}
                                        disablePopover={disablePopover || orFiltering}
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
        </div>
    )
}
