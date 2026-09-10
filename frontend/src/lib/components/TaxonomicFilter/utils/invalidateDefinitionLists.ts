import {
    TAXONOMIC_LIST_KEY_FAMILY,
    TAXONOMIC_LIST_SEARCH_KEY_FAMILY,
    invalidateTaxonomicResourcesWhere,
} from 'lib/components/TaxonomicFilter/hooks/useTaxonomicResource'
import { clearApiCache } from 'lib/components/TaxonomicFilter/infiniteListLogic'

/**
 * Matches the rebuilt picker's cache entries that hold event or property definitions. Keys are shaped
 * `[family, groupType, endpoint, ...fetch params]` (see `useGroupList.ts`), so only the first three
 * positions are read here.
 */
export function isDefinitionTaxonomicListKey(key: unknown[]): boolean {
    if (key[0] !== TAXONOMIC_LIST_KEY_FAMILY && key[0] !== TAXONOMIC_LIST_SEARCH_KEY_FAMILY) {
        return false
    }
    return typeof key[2] === 'string' && key[2].includes('_definitions')
}

export function invalidateDefinitionLists(): void {
    clearApiCache()
    invalidateTaxonomicResourcesWhere(isDefinitionTaxonomicListKey)
}
