import type { BreakdownFilter } from '~/queries/schema/schema-general'
import type { BreakdownType } from '~/types'
import { type EventPropertyFilter, type PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    BREAKDOWN_FILTER_TYPE,
    type BreakdownFilterConfig,
    type BreakdownFilterValue,
} from '../breakdown/breakdownFilterSpec'
import type { AppliedFilter } from '../filtersContext'
import {
    PROPERTY_FILTER_TYPE,
    type PropertyFilterConfig,
    type PropertyFilterValue,
} from '../property/propertyFilterSpec'
import { SELECT_FILTER_TYPE, type SelectFilterConfig, type SelectFilterValue } from '../select/selectFilterSpec'

function isPropertyFilter(filter: AppliedFilter): filter is AppliedFilter<PropertyFilterConfig, PropertyFilterValue> {
    return filter.type === PROPERTY_FILTER_TYPE && Array.isArray(filter.value)
}

function isSelectFilter(filter: AppliedFilter): filter is AppliedFilter<SelectFilterConfig, SelectFilterValue> {
    return filter.type === SELECT_FILTER_TYPE && Array.isArray(filter.value)
}

export type AnalyticsPropertyFilter = EventPropertyFilter | PersonPropertyFilter

/**
 * The applied filters an analytics query understands, as property filters to add to its `properties`. A query runner
 * calls it with `QueryRequest.filters`. A select filter's key is read as an event property. Kinds of filter it does not
 * know are left for the runner to handle.
 */
export function analyticsPropertyFilters(filters: AppliedFilter[]): AnalyticsPropertyFilter[] {
    return filters.flatMap((filter): AnalyticsPropertyFilter[] => {
        if (isPropertyFilter(filter)) {
            const { key, source } = filter.config
            return filter.value.map(({ operator, value }) => {
                const condition = { key, operator, value: value ?? operator }
                return source === 'person'
                    ? { ...condition, type: PropertyFilterType.Person }
                    : { ...condition, type: PropertyFilterType.Event }
            })
        }
        if (isSelectFilter(filter)) {
            return [
                {
                    type: PropertyFilterType.Event,
                    key: filter.config.key,
                    operator: PropertyOperator.Exact,
                    value: filter.value,
                },
            ]
        }
        return []
    })
}

function isBreakdownFilter(
    filter: AppliedFilter
): filter is AppliedFilter<BreakdownFilterConfig, BreakdownFilterValue> {
    return filter.type === BREAKDOWN_FILTER_TYPE && typeof filter.value === 'object' && filter.value !== null
}

// The query kinds whose `breakdownFilter` a dashboard breakdown replaces, as in v1's `apply_dashboard_filters`.
const KINDS_WITH_BREAKDOWN = new Set(['TrendsQuery', 'FunnelsQuery', 'RetentionQuery'])

export function analyticsBreakdownFilter(filters: AppliedFilter[], kind: string): BreakdownFilter | undefined {
    const breakdown = filters.find(isBreakdownFilter)
    if (!breakdown || !KINDS_WITH_BREAKDOWN.has(kind)) {
        return undefined
    }
    return { breakdown: breakdown.value.key, breakdown_type: breakdown.value.type as BreakdownType }
}
