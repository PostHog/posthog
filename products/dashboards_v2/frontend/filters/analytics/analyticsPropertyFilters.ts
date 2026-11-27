import { type EventPropertyFilter, type PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

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
