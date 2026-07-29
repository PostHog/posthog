import { expandRecentsForDisplay, hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    ExcludedOperators,
    ExcludedProperties,
    SelectingKeyOnly,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'
import { isFilterableExceptionPropertyForGroup } from 'lib/components/TaxonomicFilter/utils/errorTrackingProperties'

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
    selectingKeyOnly?: SelectingKeyOnly,
    excludedProperties?: ExcludedProperties
): TaxonomicDefinitionTypes[] {
    if (!recentFilterItems?.length) {
        return []
    }
    const availableTypes = new Set(taxonomicGroupTypes)
    const inScope = recentFilterItems.filter((item) => {
        if (!hasRecentContext(item) || !availableTypes.has(item._recentContext.sourceGroupType)) {
            return false
        }
        if (
            !isFilterableExceptionPropertyForGroup(item._recentContext.sourceGroupType, item._recentContext.sourceValue)
        ) {
            return false
        }
        // A group's excluded values (e.g. `message` for the logs group-by picker) must be dropped
        // from the Recent tab too, not just the group's own option list.
        const excludedValues = excludedProperties?.[item._recentContext.sourceGroupType]
        if (excludedValues?.length && excludedValues.includes(item._recentContext.sourceValue)) {
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
    return expandRecentsForDisplay(inScope, selectingKeyOnly)
}

/** Pinned items whose source group is one of the picker's groups. */
export function filterPinnedForContext(
    pinnedFilterItems: TaxonomicDefinitionTypes[],
    taxonomicGroupTypes: TaxonomicFilterGroupType[],
    excludedProperties?: ExcludedProperties
): TaxonomicDefinitionTypes[] {
    if (!pinnedFilterItems?.length) {
        return []
    }
    const availableTypes = new Set(taxonomicGroupTypes)
    return pinnedFilterItems.filter((item) => {
        if (!hasPinnedContext(item) || !availableTypes.has(item._pinnedContext.sourceGroupType)) {
            return false
        }
        if (!isFilterableExceptionPropertyForGroup(item._pinnedContext.sourceGroupType, item._pinnedContext.value)) {
            return false
        }
        const excludedValues = excludedProperties?.[item._pinnedContext.sourceGroupType]
        return !excludedValues?.includes(item._pinnedContext.value)
    })
}
