import { FacetOption } from './Facet'

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

/**
 * Ensure every selected (included or excluded) value of a dynamic facet renders even when absent
 * from the fetched list —
 * a filter from a URL or saved view can reference a value with no matches in the current scope
 * (or one below the top-N cutoff), and without a visible row it can't be seen or toggled off.
 * Missing values are prepended with a zero count. An active type-ahead search still applies to
 * injected rows, matching the server-side substring semantics of the fetched ones.
 */
export function mergeSelectedIntoOptions(fetched: FacetOption[], selected: string[], search?: string): FacetOption[] {
    const needle = (search ?? '').trim().toLowerCase()
    const fetchedValues = new Set(fetched.map((option) => option.value))
    // Dedupe: callers pass included+excluded concatenated, and a value hand-edited into both
    // polarities appears in both — without this it would inject a duplicate-keyed row.
    const missing = Array.from(new Set(selected))
        .filter((value) => !fetchedValues.has(value))
        .filter((value) => !needle || value.toLowerCase().includes(needle))
        .map((value) => ({ value, label: value, count: 0 }))
    return missing.length > 0 ? [...missing, ...fetched] : fetched
}
