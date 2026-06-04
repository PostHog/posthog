import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    ExcludedOperators,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
} from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

/** Recents whose source group is one of the visible tabs, with operators the
 *  host can't represent filtered out, and (when selecting a key only) deduped
 *  by storage key. Ported from `infiniteListLogic.contextFilteredRecentItems`. */
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

/** Pinned items whose source group is one of the visible tabs. Ported from
 *  `infiniteListLogic.contextFilteredPinnedItems`. */
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

/** Whether a recent row matches the (lower-cased) query — by its source-group
 *  display name, its PostHog core-definition label, or its recorded property
 *  filter label. Ported from `infiniteListLogic.recentItemMatchesSearch`. */
export function recentItemMatchesSearch(
    item: TaxonomicDefinitionTypes,
    query: string,
    taxonomicGroups: TaxonomicFilterGroup[]
): boolean {
    if (!hasRecentContext(item)) {
        return false
    }
    const sourceGroup = taxonomicGroups.find((g) => g.type === item._recentContext.sourceGroupType)
    const name = sourceGroup?.getName?.(item) || ('name' in item ? item.name : '') || ''
    if (name.toLowerCase().includes(query)) {
        return true
    }
    const label = sourceGroup ? getCoreFilterDefinition(name, sourceGroup.type)?.label : undefined
    if (label?.toLowerCase().includes(query)) {
        return true
    }
    const propertyFilter = item._recentContext.propertyFilter
    if (propertyFilter) {
        const recentLabel = formatPropertyLabel(propertyFilter, {})
        if (recentLabel?.toLowerCase().includes(query)) {
            return true
        }
    }
    return false
}

/** Whether a pinned row matches the (lower-cased) query. Ported from
 *  `infiniteListLogic.pinnedItemMatchesSearch`. */
export function pinnedItemMatchesSearch(
    item: TaxonomicDefinitionTypes,
    query: string,
    taxonomicGroups: TaxonomicFilterGroup[]
): boolean {
    const sourceGroup = hasPinnedContext(item)
        ? taxonomicGroups.find((g) => g.type === item._pinnedContext.sourceGroupType)
        : undefined
    const name = sourceGroup?.getName?.(item) || ('name' in item ? item.name : '') || ''
    const label = sourceGroup ? getCoreFilterDefinition(name, sourceGroup.type)?.label : undefined
    return name.toLowerCase().includes(query) || (label?.toLowerCase().includes(query) ?? false)
}
