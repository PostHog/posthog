import { SkeletonItem, TaxonomicDefinitionTypes, isSkeletonItem } from 'lib/components/TaxonomicFilter/types'

/** Search terms mapped to properties that should be promoted when that exact term is searched. */
export const PROMOTED_PROPERTIES_BY_SEARCH_TERM: Record<string, string[]> = {
    url: ['$current_url'],
    path: ['$pathname'],
    email: ['$email'],
}

/**
 * Generic promotion helper: partitions `items` so any item whose name (as
 * returned by `getName`) appears in `PROMOTED_PROPERTIES_BY_SEARCH_TERM` for
 * the given `searchQuery` floats to the front. Returns `items` unchanged when
 * the query is empty, there are no promoted names for the query, or nothing in
 * the list matches the promoted set.
 */
export function promoteMatchingBy<T>(items: T[], searchQuery: string, getName: (item: T) => string | undefined): T[] {
    const query = searchQuery.toLowerCase().trim()
    if (!query) {
        return items
    }
    const promotedNames = PROMOTED_PROPERTIES_BY_SEARCH_TERM[query]
    if (!promotedNames?.length) {
        return items
    }
    const promotedSet = new Set(promotedNames)
    const promoted: T[] = []
    const rest: T[] = []
    for (const item of items) {
        const name = getName(item)
        if (name && promotedSet.has(name)) {
            promoted.push(item)
        } else {
            rest.push(item)
        }
    }
    return promoted.length > 0 ? [...promoted, ...rest] : items
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
    return promoteMatchingBy(
        results.filter((item): item is T => !!item),
        searchQuery,
        (item) => {
            if (isSkeletonItem(item)) {
                return undefined
            }
            return 'name' in item ? (item as { name?: string }).name : undefined
        }
    )
}
