export interface FacetDefinition<TItem> {
    /** Typed before the colon, lowercase: `status`. */
    key: string
    /** Other keys that resolve to this facet: `subject` for `sends`. */
    aliases?: string[]
    /** Sentence case, shown in pills and suggestions: `Created by`. */
    label: string
    /** One short line shown next to the key in the facet list. */
    description: string
    /** Every value the item has. An item with no values never matches a positive pill and always passes a negated one. */
    getValues: (item: TItem) => string[]
    /** Display form of a stored value: `active` → `Active`, a user uuid → a name. */
    formatValue?: (value: string) => string
    /** Listed when the input is empty. Other facets are found by typing. */
    showOnFocus?: boolean
    /** Lower sorts first. */
    order?: number
}

export interface FacetFilter {
    facet: string
    value: string
    negated: boolean
}

export interface FacetSearchValue {
    filters: FacetFilter[]
    text: string
}

export interface FacetValueCount {
    value: string
    count: number
}

export type MatchesText<TItem> = (item: TItem, text: string) => boolean

export function findFacet<TItem>(facets: FacetDefinition<TItem>[], key: string): FacetDefinition<TItem> | undefined {
    const lowered = key.toLowerCase()
    return facets.find((facet) => facet.key === lowered || facet.aliases?.includes(lowered))
}

export function formatFacetValue<TItem>(facet: FacetDefinition<TItem> | undefined, value: string): string {
    return facet?.formatValue ? facet.formatValue(value) : value
}

export function sortFacets<TItem>(facets: FacetDefinition<TItem>[]): FacetDefinition<TItem>[] {
    return [...facets].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

export function facetFilterKey(filter: FacetFilter): string {
    return `${filter.negated ? '-' : ''}${filter.facet}:${filter.value.toLowerCase()}`
}

const TOKEN = /(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"|(\S*))/y

/** Reads `facet:value`, `-facet:value` and `facet:"quoted value"`. Unknown facets, empty values and repeats are dropped. */
export function parseFacetQuery<TItem>(query: string, facets: FacetDefinition<TItem>[]): FacetFilter[] {
    const filters: FacetFilter[] = []
    const seen = new Set<string>()
    let index = 0
    while (index < query.length) {
        if (/\s/.test(query[index])) {
            index++
            continue
        }
        TOKEN.lastIndex = index
        const match = TOKEN.exec(query)
        if (!match) {
            const nextSpace = query.slice(index).search(/\s/)
            index = nextSpace === -1 ? query.length : index + nextSpace
            continue
        }
        index = TOKEN.lastIndex
        const facet = findFacet(facets, match[2])
        const value = match[3] !== undefined ? match[3].replace(/\\(.)/g, '$1') : match[4]
        if (!facet || !value) {
            continue
        }
        const filter = { facet: facet.key, value, negated: match[1] === '-' }
        const key = facetFilterKey(filter)
        if (!seen.has(key)) {
            seen.add(key)
            filters.push(filter)
        }
    }
    return filters
}

export function serializeFacetValue(value: string): string {
    return /[\s"]/.test(value) ? `"${value.replace(/[\\"]/g, (char) => `\\${char}`)}"` : value
}

export function serializeFacetQuery(filters: FacetFilter[]): string {
    return filters
        .map((filter) => `${filter.negated ? '-' : ''}${filter.facet}:${serializeFacetValue(filter.value)}`)
        .join(' ')
}

function passesFilters<TItem>(item: TItem, filters: FacetFilter[], facets: FacetDefinition<TItem>[]): boolean {
    const byFacet = new Map<string, FacetFilter[]>()
    for (const filter of filters) {
        byFacet.set(filter.facet, [...(byFacet.get(filter.facet) ?? []), filter])
    }
    for (const [key, facetFilters] of byFacet) {
        const facet = findFacet(facets, key)
        if (!facet) {
            continue
        }
        const values = new Set(facet.getValues(item).map((value) => value.toLowerCase()))
        const positive = facetFilters.filter((filter) => !filter.negated)
        if (positive.length && !positive.some((filter) => values.has(filter.value.toLowerCase()))) {
            return false
        }
        if (facetFilters.some((filter) => filter.negated && values.has(filter.value.toLowerCase()))) {
            return false
        }
    }
    return true
}

/** Pills on one facet are OR, pills on different facets are AND, and the text is AND with the pills. */
export function matchesFacetQuery<TItem>(
    item: TItem,
    value: FacetSearchValue,
    facets: FacetDefinition<TItem>[],
    matchesText: MatchesText<TItem>
): boolean {
    const text = value.text.trim()
    return passesFilters(item, value.filters, facets) && (!text || matchesText(item, text))
}

/**
 * Counts each value of one facet over the items the other pills and the text let through.
 * The facet's own pills are left out, so picking one value keeps the counts of its OR alternatives.
 */
export function countFacetValues<TItem>(
    items: TItem[],
    facetKey: string,
    value: FacetSearchValue,
    facets: FacetDefinition<TItem>[],
    matchesText: MatchesText<TItem>
): FacetValueCount[] {
    const facet = findFacet(facets, facetKey)
    if (!facet) {
        return []
    }
    const others: FacetSearchValue = {
        filters: value.filters.filter((filter) => filter.facet !== facet.key),
        text: value.text,
    }
    const counts = new Map<string, FacetValueCount>()
    for (const item of items) {
        if (!matchesFacetQuery(item, others, facets, matchesText)) {
            continue
        }
        const itemValues = new Map(facet.getValues(item).map((itemValue) => [itemValue.toLowerCase(), itemValue]))
        for (const [lowered, itemValue] of itemValues) {
            const entry = counts.get(lowered)
            if (entry) {
                entry.count++
            } else {
                counts.set(lowered, { value: itemValue, count: 1 })
            }
        }
    }
    return [...counts.values()].sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
}
