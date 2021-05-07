import React from 'react'
import { useValues } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import 'scenes/actions/Actions.scss'

export function PropertyFilters({
    endpoint = null,
    propertyFilters = null,
    onChange = null,
    pageKey,
    showConditionBadge = false,
    disablePopover = false,
    popoverPlacement = null,
    style = {},
}) {
    const logic = propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey })
    const { filters } = useValues(logic)

    return (
        <div className="mb" style={style}>
            {filters?.length &&
                filters.map((item, index) => {
                    return (
                        <FilterRow
                            key={index}
                            logic={logic}
                            item={item}
                            index={index}
                            totalCount={filters.length - 1} // empty state
                            filters={filters}
                            pageKey={pageKey}
                            showConditionBadge={showConditionBadge}
                            disablePopover={disablePopover}
                            popoverPlacement={popoverPlacement}
                        />
                    )
                })}
        </div>
    )
}
