import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    isSkeletonItem,
    SkeletonItem,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

// The single source of truth for the key a recent, a pinned entry, and a group's
// own result all agree on, so the three can be compared. Recent/pinned entries key
// off their recorded source group + value; a group result keys off its own type +
// `getValue`. Everything that builds one of these keys must go through here.
export function groupItemKey(groupType: TaxonomicFilterGroupType, value: TaxonomicFilterValue): string | null {
    return value == null ? null : `${groupType}::${value}`
}

export function recentSourceKey(item: TaxonomicDefinitionTypes): string | null {
    return hasRecentContext(item)
        ? groupItemKey(item._recentContext.sourceGroupType, item._recentContext.sourceValue)
        : null
}

export function pinnedSourceKey(item: TaxonomicDefinitionTypes): string | null {
    return hasPinnedContext(item) ? groupItemKey(item._pinnedContext.sourceGroupType, item._pinnedContext.value) : null
}

// When a filter exposes a single substantive group there are no separate Recent/Pinned
// tabs to lean on, so the group's own list carries them: recent items (most-recent first)
// float to the top, then pinned, then everything else keeps its order. The list stays flat
// and deduped — each item appears once, because we reorder the group's own results in place
// rather than prepending copies. `keyOf` keys a group result the same way recent/pinned
// entries are keyed (via `groupItemKey`) so the tiers line up. Shared by the legacy
// `infiniteListLogic` and the rebuild `useGroupList`.
//
// A present synthetic aggregate row (e.g. "All events", whose value is null) leads and keeps
// its place — a promoted real item never displaces the group's own catch-all row. Skeletons
// and sparse-array holes (undefined, from a partially loaded legacy list) are left exactly
// where they are: they must never be keyed (`getValue(undefined)` throws) and must never
// float, so the virtualized loader's position math is preserved. Callers still gate the
// legacy path on a fully-loaded list; this is the defensive floor.
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
            // Holes / skeletons stay put — never keyed (would throw), never floated.
            if (item == null || isSkeletonItem(item)) {
                return { item, index, tier: REST_TIER, rank: 0 }
            }
            const key = keyOf(item)
            if (key == null) {
                // Present synthetic aggregate row (e.g. "All events") — leads, keeps its place.
                return { item, index, tier: LEADING_TIER, rank: 0 }
            }
            const rank = recentRank.get(key)
            const tier = rank !== undefined ? RECENT_TIER : pinnedKeys.has(key) ? PINNED_TIER : REST_TIER
            return { item, index, tier, rank: rank ?? 0 }
        })
        .sort((a, b) => a.tier - b.tier || (a.tier === RECENT_TIER ? a.rank - b.rank : 0) || a.index - b.index)
        .map((entry) => entry.item)
}
