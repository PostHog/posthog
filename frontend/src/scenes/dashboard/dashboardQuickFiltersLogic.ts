import { connect, kea, path, selectors } from 'kea'

import { SelectedQuickFilter, quickFiltersLogic, quickFiltersSectionLogic } from 'lib/components/QuickFilters'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, QuickFilter, QuickFilterPropertyType } from '~/types'

import type { dashboardQuickFiltersLogicType } from './dashboardQuickFiltersLogicType'

const PROPERTY_FILTER_TYPE_BY_QUICK_FILTER_TYPE: Record<QuickFilterPropertyType, PropertyFilterType> = {
    event: PropertyFilterType.Event,
    person: PropertyFilterType.Person,
    session: PropertyFilterType.Session,
    group: PropertyFilterType.Group,
    data_warehouse_person_property: PropertyFilterType.DataWarehousePersonProperty,
}

function buildPropertyFilter(
    filter: QuickFilter | undefined,
    selection: SelectedQuickFilter
): AnyPropertyFilter | null {
    const propertyTypeKey = filter?.property_type ?? 'event'
    const type = PROPERTY_FILTER_TYPE_BY_QUICK_FILTER_TYPE[propertyTypeKey] ?? PropertyFilterType.Event

    // A group property filter without group_type_index would be silently dropped by query parsing.
    // The serializer now rejects this combination at write time, but legacy rows may still exist —
    // skip them rather than emit a no-op filter that gives the user a misleading "filtered" UI.
    if (type === PropertyFilterType.Group && (filter?.group_type_index == null || filter.group_type_index < 0)) {
        return null
    }

    const base = {
        key: selection.propertyName,
        value: selection.value,
        operator: selection.operator,
        type,
    } as AnyPropertyFilter

    if (type === PropertyFilterType.Group) {
        return { ...base, group_type_index: filter!.group_type_index } as AnyPropertyFilter
    }

    return base
}

export const dashboardQuickFiltersLogic = kea<dashboardQuickFiltersLogicType>([
    path(['scenes', 'dashboard', 'dashboardQuickFiltersLogic']),

    connect(() => {
        const context = QuickFilterContext.Dashboards
        return {
            values: [
                quickFiltersSectionLogic({ context }),
                ['selectedQuickFilters'],
                quickFiltersLogic({ context }),
                ['quickFilters'],
            ],
        }
    }),

    selectors({
        // Keyed by filter ID so dashboardLogic can scope to dashboard.quick_filter_ids.
        // The QuickFilter.property_type field (added in migration 1154) determines whether the
        // resulting property filter targets events, persons, sessions, groups, or warehouse properties.
        // Quick filters without a property_type fall back to 'event' for backwards compatibility.
        quickFilterPropertyFiltersById: [
            (s) => [s.selectedQuickFilters, s.quickFilters],
            (
                selectedQuickFilters: Record<string, SelectedQuickFilter>,
                quickFilters: QuickFilter[]
            ): Record<string, AnyPropertyFilter> => {
                const filtersById = new Map(quickFilters.map((f) => [f.id, f]))
                const entries: [string, AnyPropertyFilter][] = []
                for (const [filterId, selection] of Object.entries(selectedQuickFilters)) {
                    const propertyFilter = buildPropertyFilter(filtersById.get(filterId), selection)
                    if (propertyFilter) {
                        entries.push([filterId, propertyFilter])
                    }
                }
                return Object.fromEntries(entries)
            },
        ],
    }),
])
