import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup } from 'lib/components/TaxonomicFilter/types'
import { promoteMatchingProperties } from 'lib/components/TaxonomicFilter/utils/promoteProperties'
import { TopMatchItem } from 'lib/components/TaxonomicFilter/utils/redistributeTopMatches'

export const RECENT_PINNED_PREFIX_LIMIT = 3

export interface ComposeSuggestedItemsInput {
    searchQuery: string
    /** The Suggested group's own options (promoted context-event properties),
     *  already locally filtered for the current query. */
    localResults: TaxonomicDefinitionTypes[]
    localCount: number
    /** Context-filtered recents/pinned — used as the no-query prefix. */
    contextRecents: TaxonomicDefinitionTypes[]
    contextPinned: TaxonomicDefinitionTypes[]
    /** Recents/pinned matching the current query — used in place of the prefix
     *  when a query is present. */
    recentMatches: TaxonomicDefinitionTypes[]
    pinnedMatches: TaxonomicDefinitionTypes[]
    /** Aggregated cross-tab top matches (already redistributed + deduped),
     *  appended after the local options. Only present with a query. */
    topMatches?: TaxonomicDefinitionTypes[]
}

export interface ComposedSuggestedItems {
    items: TaxonomicDefinitionTypes[]
    count: number
}

/**
 * Build the SuggestedFilters tab's rows. Mirrors the legacy
 * `infiniteListLogic.items` composition for the SuggestedFilters group:
 *   - no query: top-N recents, then top-N pinned, then the local options
 *   - with query: recents matching the query, then pinned matching it, then
 *     the locally-filtered options, with promoted properties floated to front
 * Cross-tab top-match aggregation is layered on in a later step.
 */
export function composeSuggestedItems({
    searchQuery,
    localResults,
    localCount,
    contextRecents,
    contextPinned,
    recentMatches,
    pinnedMatches,
    topMatches = [],
}: ComposeSuggestedItemsInput): ComposedSuggestedItems {
    const hasQuery = !!searchQuery.trim()
    const recentSegment = hasQuery ? recentMatches : contextRecents.slice(0, RECENT_PINNED_PREFIX_LIMIT)
    const pinnedSegment = hasQuery ? pinnedMatches : contextPinned.slice(0, RECENT_PINNED_PREFIX_LIMIT)
    const combined = [...recentSegment, ...pinnedSegment, ...localResults, ...topMatches]
    return {
        items: hasQuery ? promoteMatchingProperties(combined, searchQuery) : combined,
        count: recentSegment.length + pinnedSegment.length + localCount + topMatches.length,
    }
}

/**
 * Drop top-match rows that duplicate a recent/pinned row already shown, keyed
 * by the row's source group + value (so "Recent · pageview" doesn't stack above
 * "Events · pageview"). Mirrors the legacy `infiniteListLogic.dedupedTopMatches`.
 */
export function dedupeTopMatches(
    topMatches: TopMatchItem[],
    shownRecents: TaxonomicDefinitionTypes[],
    shownPinned: TaxonomicDefinitionTypes[],
    groups: TaxonomicFilterGroup[]
): TopMatchItem[] {
    if (topMatches.length === 0) {
        return []
    }
    const dedupeKeys = new Set<string>()
    for (const item of shownRecents) {
        if (hasRecentContext(item) && item._recentContext.sourceValue != null) {
            dedupeKeys.add(`${item._recentContext.sourceGroupType}::${item._recentContext.sourceValue}`)
        }
    }
    for (const item of shownPinned) {
        if (hasPinnedContext(item) && item._pinnedContext.value != null) {
            dedupeKeys.add(`${item._pinnedContext.sourceGroupType}::${item._pinnedContext.value}`)
        }
    }
    if (dedupeKeys.size === 0) {
        return topMatches
    }
    const groupsByType = new Map(groups.map((g) => [g.type, g]))
    return topMatches.filter((item) => {
        const value = groupsByType.get(item.group)?.getValue?.(item) ?? null
        return value == null || !dedupeKeys.has(`${item.group}::${value}`)
    })
}
