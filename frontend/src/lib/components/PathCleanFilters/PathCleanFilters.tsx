import React, { CSSProperties } from 'react'
import { useValues } from 'kea'
import 'scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Placement } from '@popperjs/core'
import { FilterRow } from '../PropertyFilters/components/FilterRow'
import { PathRegexPopup } from './PathCleanFilter'
import { teamLogic } from 'scenes/teamLogic'

interface PropertyFiltersProps {
    endpoint?: string | null
    onChange: (filters: Record<string, any>[]) => void
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
    pageKey,
    onChange,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement = null,
    taxonomicPopoverPlacement = undefined,
    style = {},
    showNestedArrow = false,
}: PropertyFiltersProps): JSX.Element {
    const { path_cleaning_filters_with_new, currentTeam } = useValues(teamLogic)

    const onRemove = (index: number): void => {
        const newState = (currentTeam?.path_cleaning_filters || []).filter((_, i) => i !== index)
        onChange(newState)
    }

    return (
        <div className="mb" style={style}>
            {path_cleaning_filters_with_new.length &&
                path_cleaning_filters_with_new.map((item, index) => {
                    return (
                        <FilterRow
                            key={index}
                            item={item}
                            index={index}
                            totalCount={path_cleaning_filters_with_new.length - 1} // empty state
                            filters={path_cleaning_filters_with_new}
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
                                            onChange([...(currentTeam?.path_cleaning_filters || []), newItem])
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
