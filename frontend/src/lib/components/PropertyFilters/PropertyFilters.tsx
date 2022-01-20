import React, { CSSProperties } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'

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
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
    greyBadges?: boolean
    eventNames?: string[]
    pinnedFilters?: string[]
}

export function PropertyFilters({
    propertyFilters = null,
    onChange = null,
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
    const { filters } = useValues(propertyFilterLogic(logicProps))
    const { remove } = useActions(propertyFilterLogic(logicProps))

    return (
        <div className="property-filters" style={style}>
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
                                pinnedFilters={pinnedFilters}
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
