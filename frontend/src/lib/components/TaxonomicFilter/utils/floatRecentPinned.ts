import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import { isSkeletonItem, SkeletonItem, TaxonomicDefinitionTypes } from 'lib/components/TaxonomicFilter/types'

// The two key builders must stay format-aligned: recent and pinned rows dedupe
// against each other (and against a group's own results) only because both
// produce `sourceGroupType::value`.
export function recentSourceKey(item: TaxonomicDefinitionTypes): string | null {
    return hasRecentContext(item) && item._recentContext.sourceValue != null
        ? `${item._recentContext.sourceGroupType}::${item._recentContext.sourceValue}`
        : null
}

export function pinnedSourceKey(item: TaxonomicDefinitionTypes): string | null {
    return hasPinnedContext(item) && item._pinnedContext.value != null
        ? `${item._pinnedContext.sourceGroupType}::${item._pinnedContext.value}`
        : null
}

// When a filter exposes a single substantive group there are no separate Recent/Pinned
// tabs to lean on, so the group's own list carries them: recent items (most-recent first)
// float to the top, then pinned, then everything else keeps its order. The list stays flat
// and deduped — each item appears once, because we reorder the group's own results in place
// rather than prepending copies. `keyOf` keys a group result the same way recent/pinned
// entries are keyed (`sourceGroupType::value`) so the tiers line up. Shared by the legacy
// `infiniteListLogic` and the rebuild `useGroupList`.
//
// Rows we can't key (skeletons, and synthetic aggregate rows like "All events" whose value
// is null) lead and keep their original order — a recent/pinned real item never displaces
// the group's own leading catch-all row.
const LEADING_TIER = -1
const RECENT_TIER = 0
const PINNED_TIER = 1
const REST_TIER = 2

export function floatRecentAndPinnedToTop(
    items: (TaxonomicDefinitionTypes | SkeletonItem)[],
    keyOf: (item: TaxonomicDefinitionTypes) => string | null,
    recentItems: TaxonomicDefinitionTypes[],
    pinnedItems: TaxonomicDefinitionTypes[]
): (TaxonomicDefinitionTypes | SkeletonItem)[] {
    const recentRank = new Map<string, number>()
    recentItems.forEach((item, rank) => {
        const key = recentSourceKey(item)
        if (key != null && !recentRank.has(key)) {
            recentRank.set(key, rank)
        }
    })
    const pinnedKeys = new Set<string>()
    pinnedItems.forEach((item) => {
        const key = pinnedSourceKey(item)
        if (key != null) {
            pinnedKeys.add(key)
        }
    })
    if (recentRank.size === 0 && pinnedKeys.size === 0) {
        return items
    }
    return items
        .map((item, index) => {
            const key = isSkeletonItem(item) ? null : keyOf(item)
            const recency = key != null ? recentRank.get(key) : undefined
            const tier =
                key == null
                    ? LEADING_TIER
                    : recency !== undefined
                      ? RECENT_TIER
                      : pinnedKeys.has(key)
                        ? PINNED_TIER
                        : REST_TIER
            return { item, index, tier, recency: recency ?? 0 }
        })
        .sort((a, b) => a.tier - b.tier || (a.tier === RECENT_TIER ? a.recency - b.recency : 0) || a.index - b.index)
        .map((entry) => entry.item)
}
