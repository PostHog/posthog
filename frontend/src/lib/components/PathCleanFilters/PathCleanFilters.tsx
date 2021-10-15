import React, { CSSProperties } from 'react'
import { useValues, BindLogic } from 'kea'
import 'scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { propertyFilterLogic } from '../PropertyFilters/propertyFilterLogic'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { PathRegexPopup } from './PathCleanFilter'

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

export function PathCleanFilters({
    propertyFilters = null,
    onChange = null,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    style = {},
    showNestedArrow = false,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey }
    const { filters } = useValues(propertyFilterLogic(logicProps))

    // const { updateCurrentTeam } = useActions(teamLogic)
    // const { currentTeam } = useValues(teamLogic)

    return (
        <div className="mb" style={style}>
            <BindLogic logic={propertyFilterLogic} props={logicProps}>
                {filters?.length &&
                    filters?.map((item, index) => {
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
                                showNestedArrow={showNestedArrow}
                                label={'Add rule'}
                                filterComponent={() => {
                                    return <PathRegexPopup />
                                }}
                            />
                        )
                    })}
            </BindLogic>
        </div>
    )
}
