import React, { CSSProperties } from 'react'
import '../../../scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { PathRegexPopup } from './PathCleanFilter'

interface PropertyFiltersProps {
    endpoint?: string | null
    onChange: (newItem: Record<string, any>) => void
    onRemove: (index: number) => void
    pathCleaningFilters: Record<string, any>[]
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
    taxonomicPopoverPlacement?: Placement
    style?: CSSProperties
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
}

export function PathCleanFilters({
    pageKey,
    onChange,
    onRemove,
    pathCleaningFilters,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    style = {},
    showNestedArrow = false,
}: PropertyFiltersProps): JSX.Element {
    return (
        <div className="mb" style={style}>
            {pathCleaningFilters.length > 0 &&
                pathCleaningFilters.map((item, index) => {
                    return (
                        <FilterRow
                            key={index}
                            item={item}
                            index={index}
                            totalCount={pathCleaningFilters.length - 1} // empty state
                            filters={pathCleaningFilters}
                            pageKey={pageKey}
                            showConditionBadge={showConditionBadge}
                            disablePopover={disablePopover}
                            popoverPlacement={popoverPlacement}
                            taxonomicPopoverPlacement={taxonomicPopoverPlacement}
                            showNestedArrow={showNestedArrow}
                            label={'Add rule'}
                            onRemove={onRemove}
                            filterComponent={(onComplete) => {
                                return (
                                    <PathRegexPopup
                                        item={item}
                                        onClose={onComplete}
                                        onComplete={(newItem) => {
                                            onChange(newItem)
                                            onComplete()
                                        }}
                                    />
                                )
                            }}
                        />
                    )
                })}
        </div>
    )
}
