import { isEmptyProperty } from 'lib/components/PropertyFilters/utils'

import { TriggerPropertyFilter } from '~/lib/components/IngestionControls/types'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

/** Convert our trigger property filters to the AnyPropertyFilter format PropertyFilters expects. */
export function triggerFiltersToPropertyFilters(filters: TriggerPropertyFilter[]): AnyPropertyFilter[] {
    return filters.map(
        (f) =>
            ({
                key: f.key,
                type: f.type === 'person' ? PropertyFilterType.Person : PropertyFilterType.Event,
                operator: (f.operator as PropertyOperator) || PropertyOperator.Exact,
                value: f.value ?? '',
            }) as AnyPropertyFilter
    )
}

/** Convert PropertyFilters output back to our trigger property filter format. Drops half-typed rows
 * (a key picked but no value yet), which JSON would send without a `value` and the API rejects. */
export function propertyFiltersToTriggerFilters(filters: AnyPropertyFilter[]): TriggerPropertyFilter[] {
    return filters
        .filter((f) => f.key && !isEmptyProperty(f))
        .map((f) => ({
            key: f.key!,
            type: f.type === PropertyFilterType.Person ? ('person' as const) : ('event' as const),
            operator: 'operator' in f ? (f.operator as TriggerPropertyFilter['operator']) : 'exact',
            value: (f as { value: TriggerPropertyFilter['value'] }).value,
        }))
}
