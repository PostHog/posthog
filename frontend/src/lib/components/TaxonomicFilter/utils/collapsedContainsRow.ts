import { PropertyFilterType, PropertyOperator } from '~/types'

import { QuickFilterItem, TaxonomicFilterGroupType } from '../types'

/** Groups that collapse to a single "URL contains <query>" suggestion instead of
 *  listing every matching value, and are not offered as a standalone value picker.
 *  People filtering by URL overwhelmingly want a contains match, so one synthetic
 *  row (when any URL matches) beats a wall of exact URLs. Shared by the legacy
 *  picker (`infiniteListLogic`) and the rebuild menu (`menu/Combobox`) so both arms
 *  of the experiment collapse identically.
 *
 *  - `PageviewUrls` is the property-filter flavour ($current_url IContains <query>).
 *  - `PageviewEvents` is the series flavour: a `$pageview` event filtered by the same
 *    `$current_url IContains <query>`. Both hit the same URL-values endpoint. */
export const COLLAPSED_TO_CONTAINS_ROW: ReadonlySet<TaxonomicFilterGroupType> = new Set([
    TaxonomicFilterGroupType.PageviewUrls,
    TaxonomicFilterGroupType.PageviewEvents,
])

export function urlContainsRowLabel(query: string): string {
    return `URL contains "${query}"`
}

/** Synthetic row committed as `$current_url IContains <query>`. Returned as a
 *  `QuickFilterItem` so it flows through the existing `isQuickFilterItem` handling
 *  in the property-, universal-, and series (ActionFilterRow) hosts, committing the
 *  same filter the per-URL value picker used to — without listing every matching URL.
 *
 *  For the `PageviewEvents` (series) group the shortcut also carries `eventName:
 *  '$pageview'` so the host expands it into a `$pageview` event plus the property
 *  filter, rather than a bare property filter. */
export function buildUrlContainsShortcut(query: string, groupType?: TaxonomicFilterGroupType): QuickFilterItem {
    return {
        _type: 'quick_filter',
        name: urlContainsRowLabel(query),
        filterValue: query,
        operator: PropertyOperator.IContains,
        propertyKey: '$current_url',
        propertyFilterType: PropertyFilterType.Event,
        isContainsShortcut: true,
        ...(groupType === TaxonomicFilterGroupType.PageviewEvents ? { eventName: '$pageview' } : {}),
    }
}

/** A row that is the synthetic "URL contains <query>" shortcut (tagged on the item). */
export function isContainsShortcutItem(item: unknown): boolean {
    return !!item && typeof item === 'object' && (item as { isContainsShortcut?: boolean }).isContainsShortcut === true
}
