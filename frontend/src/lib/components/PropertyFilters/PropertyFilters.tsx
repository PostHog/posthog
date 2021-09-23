import React, { CSSProperties } from 'react'
import { useValues, BindLogic } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import 'scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    style?: CSSProperties
    groupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
}

export function PropertyFilters({
    propertyFilters = null,
    onChange = null,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    groupTypes,
    style = {},
    showNestedArrow = false,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filters } = useValues(propertyFilterLogic(logicProps))

    return (
        <div className="mb" style={style}>
            <BindLogic logic={propertyFilterLogic} props={logicProps}>
                {filters?.length &&
                    filters.map((item, index) => {
                        return (
                            <FilterRow
                                key={index}
                                item={item}
                                index={index}
                                totalCount={filters.length - 1} // empty state
                                filters={filters}
                                pageKey={pageKey}
                                showConditionBadge={showConditionBadge}
                                disablePopover={disablePopover}
                                popoverPlacement={popoverPlacement}
                                taxonomicPopoverPlacement={taxonomicPopoverPlacement}
                                groupTypes={groupTypes}
                                showNestedArrow={showNestedArrow}
                            />
                        )
                    })}
            </BindLogic>
        </div>
    )
}
