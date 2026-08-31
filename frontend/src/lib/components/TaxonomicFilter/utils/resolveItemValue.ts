import { hasRecentContext } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

// The single source of truth for the value a selected row commits with, so that a click and a
// keypress cannot resolve the same row differently. A recent row is stored as `{ name, id? }`,
// so the source group's `getValue` returns undefined for it: EventMetadata reads `id`, and
// Persons reads a distinct id. The canonical `sourceValue`, recorded at first selection, is the
// fallback. Every path that turns a row into a value must go through here, because a path that
// resolves its own value commits a different filter than the other paths do, with no error.
export function resolveItemValue(
    item: TaxonomicDefinitionTypes | undefined,
    itemGroup: TaxonomicFilterGroup | undefined
): TaxonomicFilterValue | undefined {
    if (!item) {
        return null
    }
    if (hasRecentContext(item)) {
        return item._recentContext.sourceValue ?? itemGroup?.getValue?.(item)
    }
    return itemGroup?.getValue?.(item)
}
