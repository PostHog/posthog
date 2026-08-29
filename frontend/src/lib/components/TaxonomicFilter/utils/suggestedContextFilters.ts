import { expandRecentsForDisplay, hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    ExcludedOperators,
    ExcludedProperties,
    SelectingKeyOnly,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'

/*
 * The legacy `infiniteListLogic` picker and the rebuild both call
 * `filterPinnedForContext`, so a change to pinned behaviour reaches both.
 * `filterRecentsForContext` is not shared: `infiniteListLogic` holds its own
 * copy of the same rule in `contextFilteredRecentItems`, so a change to recents
 * behaviour must be made in both places until the legacy picker is retired.
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
