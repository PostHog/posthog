import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    ExcludedOperators,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'

/*
 * These mirror the legacy `infiniteListLogic` context-filter selectors
 * (`contextFilteredRecentItems` / `contextFilteredPinnedItems`). It's a
 * deliberate fork, not a shared util: the rebuild and the legacy kea picker
 * are independent code paths, and the legacy one is being retired with the
 * rest of `infiniteListLogic`. Until then, behaviour changes here that should
 * also apply to the legacy picker must be made in both places.
 */

/** Recents whose source group is one of the picker's groups, with operators the
 *  host can't represent filtered out, and (when selecting a key only) deduped by
 *  storage key, so the picker stops surfacing recents that belong to a
 *  different picker. */
export function filterRecentsForContext(
    recentFilterItems: TaxonomicDefinitionTypes[],
    taxonomicGroupTypes: TaxonomicFilterGroupType[],
    excludedOperators?: ExcludedOperators,
    selectingKeyOnly?: boolean
): TaxonomicDefinitionTypes[] {
    if (!recentFilterItems?.length) {
        return []
    }
    const availableTypes = new Set(taxonomicGroupTypes)
    const inScope = recentFilterItems.filter((item) => {
        if (!hasRecentContext(item) || !availableTypes.has(item._recentContext.sourceGroupType)) {
            return false
        }
        const excludedForGroup = excludedOperators?.[item._recentContext.sourceGroupType]
        if (excludedForGroup?.length) {
            const propertyFilter = item._recentContext.propertyFilter
            const operator = propertyFilter && 'operator' in propertyFilter ? propertyFilter.operator : undefined
            if (operator && excludedForGroup.includes(operator)) {
                return false
            }
        }
        return true
    })
    if (!selectingKeyOnly) {
        return inScope
    }
    const seen = new Set<string>()
    const dedupedItems: TaxonomicDefinitionTypes[] = []
    for (const item of inScope) {
        if (!hasRecentContext(item)) {
            continue
        }
        // Dedup by the persisted storage key (source group + value), not by
        // item.name — for groups like Cohorts/Actions the name is a display
        // label that can be unstable, while the stored value is canonical.
        const dedupKey = `${item._recentContext.sourceGroupType}::${item._recentContext.sourceValue ?? ''}`
        if (seen.has(dedupKey)) {
            continue
        }
        seen.add(dedupKey)
        const { propertyFilter: _propertyFilter, ...restContext } = item._recentContext
        dedupedItems.push({ ...item, _recentContext: restContext } as unknown as TaxonomicDefinitionTypes)
    }
    return dedupedItems
}

/** Pinned items whose source group is one of the picker's groups. */
export function filterPinnedForContext(
    pinnedFilterItems: TaxonomicDefinitionTypes[],
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
): TaxonomicDefinitionTypes[] {
    if (!pinnedFilterItems?.length) {
        return []
    }
    const availableTypes = new Set(taxonomicGroupTypes)
    return pinnedFilterItems.filter(
        (item) => hasPinnedContext(item) && availableTypes.has(item._pinnedContext.sourceGroupType)
    )
}
