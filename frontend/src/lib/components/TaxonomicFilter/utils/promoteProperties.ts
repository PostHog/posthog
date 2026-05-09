import { SkeletonItem, TaxonomicDefinitionTypes, isSkeletonItem } from 'lib/components/TaxonomicFilter/types'

/** Search terms mapped to properties that should be promoted when that exact term is searched. */
export const PROMOTED_PROPERTIES_BY_SEARCH_TERM: Record<string, string[]> = {
    url: ['$current_url'],
    email: ['$email'],
}

/**
 * If the search query matches a promoted property's search terms, move that property
 * to the top of results so users find it quickly.
 *
 * `getName` is an optional extractor for callers whose `T` wraps the
 * underlying definition (e.g. `MenuFilterEntry { item, name, … }`) — when
 * omitted, falls back to reading `item.name` directly off `T`.
 */
export function promoteMatchingProperties<T>(results: T[], searchQuery: string, getName?: (item: T) => string): T[] {
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
        if (isSkeletonItem(item as unknown as TaxonomicDefinitionTypes | SkeletonItem)) {
            rest.push(item)
            continue
        }
        const name = getName
            ? getName(item)
            : 'name' in (item as object)
              ? ((item as { name?: string }).name ?? '')
              : ''
        if (name && promotedPropertyNameSet.has(name)) {
            promoted.push(item)
        } else {
            rest.push(item)
        }
    }

    return promoted.length > 0 ? [...promoted, ...rest] : results
}
