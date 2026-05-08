import { SkeletonItem, TaxonomicDefinitionTypes, isSkeletonItem } from 'lib/components/TaxonomicFilter/types'

/** Search terms mapped to properties that should be promoted when that exact term is searched. */
export const PROMOTED_PROPERTIES_BY_SEARCH_TERM: Record<string, string[]> = {
    url: ['$current_url'],
    email: ['$email'],
}

/**
 * If the search query matches a promoted property's search terms, move that property
 * to the top of results so users find it quickly.
 */
export function promoteMatchingProperties<T extends TaxonomicDefinitionTypes | SkeletonItem>(
    results: T[],
    searchQuery: string
): T[] {
    if (!searchQuery) {
        return results
    }

    const query = searchQuery.toLowerCase().trim()
    const promotedPropertyNames = PROMOTED_PROPERTIES_BY_SEARCH_TERM[query]
    if (!promotedPropertyNames?.length) {
        return results
    }

    const promotedPropertyNameSet = new Set(promotedPropertyNames)
    const promoted: T[] = []
    const rest: T[] = []

    for (const item of results as (T | undefined)[]) {
        if (!item) {
            continue
        }
        if (isSkeletonItem(item)) {
            rest.push(item)
            continue
        }
        const name = 'name' in item ? (item as { name?: string }).name : undefined
        if (name && promotedPropertyNameSet.has(name)) {
            promoted.push(item)
        } else {
            rest.push(item)
        }
    }

    return promoted.length > 0 ? [...promoted, ...rest] : results
}
