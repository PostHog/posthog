/** The fields the shared rail needs from a product's facet config to search and group it. */
export interface FacetGroupItem {
    key: string
    title: string
    group: string
}

/**
 * Filter facets by a free-text query matching the field name or its group (case-insensitive
 * substring) — powers the rail's "search facets" box. A blank query returns everything, so
 * `facetsByGroup` then drops any group left with no matching facets for free.
 */
export function filterFacetsByName<T extends FacetGroupItem>(facets: T[], query: string): T[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return facets
    }
    return facets.filter(
        (facet) => facet.title.toLowerCase().includes(needle) || facet.group.toLowerCase().includes(needle)
    )
}

/** Group facets by `group`, preserving first-appearance order of both groups and facets. */
export function facetsByGroup<T extends FacetGroupItem>(facets: T[]): [string, T[]][] {
    const groups: [string, T[]][] = []
    for (const facet of facets) {
        const existing = groups.find(([group]) => group === facet.group)
        if (existing) {
            existing[1].push(facet)
        } else {
            groups.push([facet.group, [facet]])
        }
    }
    return groups
}
