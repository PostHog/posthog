import { TaxonomicDefinitionTypes } from 'lib/components/TaxonomicFilter/types'
import { promoteMatchingProperties } from 'lib/components/TaxonomicFilter/utils/promoteProperties'

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
}: ComposeSuggestedItemsInput): ComposedSuggestedItems {
    const hasQuery = !!searchQuery.trim()
    const recentSegment = hasQuery ? recentMatches : contextRecents.slice(0, RECENT_PINNED_PREFIX_LIMIT)
    const pinnedSegment = hasQuery ? pinnedMatches : contextPinned.slice(0, RECENT_PINNED_PREFIX_LIMIT)
    const combined = [...recentSegment, ...pinnedSegment, ...localResults]
    return {
        items: hasQuery ? promoteMatchingProperties(combined, searchQuery) : combined,
        count: recentSegment.length + pinnedSegment.length + localCount,
    }
}
