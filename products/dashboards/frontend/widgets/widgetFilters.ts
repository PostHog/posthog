import { FilterLogicalOperator, PropertyFilterType, type UniversalFiltersGroup } from '~/types'

import type { WidgetFilterConfigRecord } from '../widget_types/configSchemas'

/** Converts persisted widget `config.widgetFilters` into a HogQL/universal filter group. */
export function buildFilterGroupFromWidgetFilters(
    widgetFilters: WidgetFilterConfigRecord | undefined
): UniversalFiltersGroup | undefined {
    const selections = widgetFilters ? Object.values(widgetFilters) : []
    if (selections.length === 0) {
        return undefined
    }

    const filtersFromWidgetFilters = selections.map((entry) => {
        const filterValue = entry.value === null ? undefined : Array.isArray(entry.value) ? entry.value : [entry.value]

        return {
            type: PropertyFilterType.Event,
            key: entry.propertyName,
            operator: entry.operator,
            ...(filterValue !== undefined && { value: filterValue }),
        }
    })

    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: filtersFromWidgetFilters,
            },
        ],
    } as UniversalFiltersGroup
}
