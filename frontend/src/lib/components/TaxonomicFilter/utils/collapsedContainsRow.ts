import { PropertyFilterType, PropertyOperator } from '~/types'

import { QuickFilterItem, TaxonomicFilterGroupType } from '../types'

/** Groups that collapse to a single "URL contains <query>" suggestion instead of
 *  listing every matching value, and are not offered as a standalone value picker.
 *  People filtering by URL overwhelmingly want a contains match, so one synthetic
 *  row (when any URL matches) beats a wall of exact URLs. Shared by the legacy
 *  picker (`infiniteListLogic`) and the rebuild menu (`menu/Combobox`) so both arms
 *  of the experiment collapse identically. */
export const COLLAPSED_TO_CONTAINS_ROW: ReadonlySet<TaxonomicFilterGroupType> = new Set([
    TaxonomicFilterGroupType.PageviewUrls,
])

export function urlContainsRowLabel(query: string): string {
    return `URL contains "${query}"`
}

/** Synthetic row committed as `$current_url IContains <query>`. Returned as a
 *  `QuickFilterItem` so it flows through the existing `isQuickFilterItem` handling
 *  in the property- and universal-filter hosts, committing the same filter the
 *  per-URL value picker used to — without listing every matching URL. */
export function buildUrlContainsShortcut(query: string): QuickFilterItem {
    return {
        _type: 'quick_filter',
        name: urlContainsRowLabel(query),
        filterValue: query,
        operator: PropertyOperator.IContains,
        propertyKey: '$current_url',
        propertyFilterType: PropertyFilterType.Event,
        isContainsShortcut: true,
    }
}
