import { pluralize } from 'lib/utils'
import {
    BASE_MATH_DEFINITIONS,
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    PROPERTY_MATH_DEFINITIONS,
    apiValueToMathType,
} from 'scenes/trends/mathsLogic'

import { ActionFilter } from '~/types'

function getMathLabel(filter: ActionFilter): string {
    const mathType = apiValueToMathType(filter.math, filter.math_group_type_index ?? null)
    const allDefs = { ...BASE_MATH_DEFINITIONS, ...COUNT_PER_ACTOR_MATH_DEFINITIONS, ...PROPERTY_MATH_DEFINITIONS }
    const def = allDefs[mathType as keyof typeof allDefs]
    return def?.shortName || 'count'
}

/**
 * Compact single-line series row for the editor panels layout.
 * Renders: [badge] [event icon + name] · [math] [filter count] [⋯]
 */
export function compactSeriesRowRenderer(props: Record<string, JSX.Element | string | undefined>): JSX.Element {
    const { seriesIndicator, filter, propertyFiltersButton, filterData } = props
    const actionFilter = filterData as unknown as ActionFilter | undefined
    const filterCount = actionFilter?.properties?.length || 0
    const mathLabel = actionFilter ? getMathLabel(actionFilter) : ''

    return (
        <div className="flex items-center gap-1.5 w-full min-h-[36px]">
            <div className="shrink-0">{seriesIndicator}</div>
            <div className="flex-1 min-w-0 overflow-hidden">{filter}</div>
            {mathLabel && <span className="text-xs text-secondary whitespace-nowrap shrink-0">{mathLabel}</span>}
            {filterCount > 0 && (
                <span className="text-[11px] text-secondary bg-surface-tertiary rounded px-1 py-0.5 whitespace-nowrap shrink-0">
                    {pluralize(filterCount, 'filter')}
                </span>
            )}
            <div className="shrink-0">{propertyFiltersButton}</div>
        </div>
    )
}
