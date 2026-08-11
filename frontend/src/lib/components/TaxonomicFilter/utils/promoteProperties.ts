import { SkeletonItem, TaxonomicDefinitionTypes, isSkeletonItem } from 'lib/components/TaxonomicFilter/types'

/** Search terms mapped to properties that should be promoted when that exact term is searched. */
export const PROMOTED_PROPERTIES_BY_SEARCH_TERM: Record<string, string[]> = {
    url: ['$current_url'],
    path: ['$pathname'],
    email: ['$email'],
}

/**
 * Generic promotion helper: partitions `items` so the most relevant matches for
 * `searchQuery` float to the front, in this order:
 *   1. names mapped from the query in `PROMOTED_PROPERTIES_BY_SEARCH_TERM`
 *      (e.g. `email` -> `$email`),
 *   2. names that exactly equal the query, so a short generic term like `id`
 *      beats substring-only matches such as `organization_id` or `device_id`.
 * Everything else keeps its order below. Returns `items` unchanged when the
 * query is empty or nothing floats.
 */
export function promoteMatchingBy<T>(items: T[], searchQuery: string, getName: (item: T) => string | undefined): T[] {
    const query = searchQuery.toLowerCase().trim()
    if (!query) {
        return items
    }
    const promotedSet = new Set(PROMOTED_PROPERTIES_BY_SEARCH_TERM[query] ?? [])
    const promoted: T[] = []
    const exact: T[] = []
    const rest: T[] = []
    for (const item of items) {
        const name = getName(item)
        if (name && promotedSet.has(name)) {
            promoted.push(item)
        } else if (name && name.toLowerCase() === query) {
            exact.push(item)
        } else {
            rest.push(item)
        }
    }
    return promoted.length > 0 || exact.length > 0 ? [...promoted, ...exact, ...rest] : items
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
