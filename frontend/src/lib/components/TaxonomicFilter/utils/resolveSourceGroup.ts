import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

/** The group a row originated from, when it's a recent/pinned row that was
 *  surfaced under a different (meta) tab. Undefined for plain rows. */
export function getSourceGroupType(item: TaxonomicDefinitionTypes): TaxonomicFilterGroupType | undefined {
    if (hasRecentContext(item)) {
        return item._recentContext.sourceGroupType
    }
    if (hasPinnedContext(item)) {
        return item._pinnedContext.sourceGroupType
    }
    return undefined
}

/** Resolve the group whose `getValue`/`getName` should drive a row. Recent and
 *  pinned rows carry their original source group; top-match rows carry a
 *  `group` tag. Falls back to the tab the row is displayed under. Mirrors the
 *  legacy `getItemGroup` in `InfiniteList.tsx` so cross-group rows resolve to
 *  the same value (e.g. a recent Action keeps its `id`, not its label). */
export function resolveItemGroup(
    item: TaxonomicDefinitionTypes,
    groups: TaxonomicFilterGroup[],
    fallbackGroup: TaxonomicFilterGroup
): TaxonomicFilterGroup {
    const sourceType = getSourceGroupType(item)
    if (sourceType) {
        const sourceGroup = groups.find((g) => g.type === sourceType)
        if (sourceGroup) {
            return sourceGroup
        }
    } else if (item && 'group' in item) {
        const taggedGroup = groups.find((g) => (item as { group?: TaxonomicFilterGroupType }).group === g.type)
        if (taggedGroup) {
            return taggedGroup
        }
    }
    return fallbackGroup
}

/** Value for a row, resolved against its source group when it's a cross-group
 *  (recent/pinned/top-match) row. */
export function resolveItemValue(
    item: TaxonomicDefinitionTypes,
    groups: TaxonomicFilterGroup[],
    fallbackGroup: TaxonomicFilterGroup
): TaxonomicFilterValue {
    return resolveItemGroup(item, groups, fallbackGroup).getValue?.(item) ?? null
}
