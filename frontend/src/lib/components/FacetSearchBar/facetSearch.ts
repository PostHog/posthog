export interface FacetFilter {
    facet: string
    value: string
    negated: boolean
}

/** The bar's controlled state: the pills and the free text around them. */
export interface FacetSearchValue {
    filters: FacetFilter[]
    text: string
}

export interface FacetValueOption {
    value: string
    /** Shown in suggestions and pills instead of `formatValue(value)`. */
    label?: string
    /** Shown next to the value when known. */
    count?: number
}

export interface FacetDefinitionBase {
    /** Typed before the colon, lowercase: `status`. */
    key: string
    /** Other keys that resolve to this facet: `creator` for `created-by`. */
    aliases?: string[]
    /** Sentence case, shown in pills and suggestions: `Created by`. */
    label: string
    /** One short line shown next to the key in the facet list. */
    description: string
    /** Display form of a stored value: `active` → `Active`, a user uuid → a name. */
    formatValue?: (value: string) => string
    /** Listed when the input is empty. Other facets are found by typing. */
    showOnFocus?: boolean
    /** Lower sorts first. */
    order?: number
}

/** Client mode: values and counts come from the rows. */
export interface ClientFacet<TRow> extends FacetDefinitionBase {
    /** Every value the row has. A row with no values never matches a positive pill and always passes a negated one. */
    getValues: (row: TRow) => string[]
}

/** Gets the values for a search as typed, after `facet:` or as a bare word. The bar shows them unfiltered. */
export type LoadFacetValues = (search: string) => Promise<FacetValueOption[]>

/** Server mode: the facet lists its values up front, or loads them as the user types. */
export type ServerFacet = FacetDefinitionBase &
    ({ values: FacetValueOption[]; loadValues?: never } | { loadValues: LoadFacetValues; values?: never })

/** Client mode: the rows the browser holds, and how the free text matches one of them. */
export interface FacetSearchRows<TRow> {
    rows: TRow[]
    matchesText: (row: TRow, text: string) => boolean
}

/** Server mode: what to send to an API. Values on one facet are OR, facets are AND, `exclude` negates. */
export interface FacetQuery {
    text: string
    facets: Record<string, { include: string[]; exclude: string[] }>
}

export function findFacet<TFacet extends FacetDefinitionBase>(facets: TFacet[], key: string): TFacet | undefined {
    const lowered = key.toLowerCase()
    return facets.find((facet) => facet.key === lowered || facet.aliases?.includes(lowered))
}

export function formatFacetValue(facet: FacetDefinitionBase | undefined, value: string): string {
    return facet?.formatValue ? facet.formatValue(value) : value
}

export function facetFilterKey(filter: FacetFilter): string {
    return `${filter.negated ? '-' : ''}${filter.facet}:${filter.value}`
}

const TOKEN = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"|([^\s"]+)(?=\s|$))/g
const TOKEN_FOLLOWED_BY_SPACE = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"|([^\s"]+)(?=\s))/g
const DRAFT_TOKEN = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"?|(\S*))$/
const QUOTED_TOKEN_START = /-?[\w-]+:"/y

function isSpace(char: string): boolean {
    return /\s/.test(char)
}

function openQuotedTokenStart(input: string): number {
    let index = 0
    while (index < input.length) {
        if (isSpace(input[index])) {
            index++
            continue
        }
        QUOTED_TOKEN_START.lastIndex = index
        if (QUOTED_TOKEN_START.test(input)) {
            const tokenStart = index
            index = QUOTED_TOKEN_START.lastIndex
            while (index < input.length && input[index] !== '"') {
                index += input[index] === '\\' ? 2 : 1
            }
            if (index >= input.length) {
                return tokenStart
            }
        }
        while (index < input.length && !isSpace(input[index])) {
            index++
        }
    }
    return input.length
}

function unescapeFacetValue(quoted: string): string {
    return quoted.replace(/\\(.)/g, '$1')
}

/**
 * Takes the complete, known `facet:value` tokens out of the input. Unknown facets stay as typed.
 * With `untilEnd`, a token at the very end counts as complete; the bar leaves it as a draft until a space follows.
 */
export function extractFacetFilters(
    input: string,
    facets: FacetDefinitionBase[],
    { untilEnd }: { untilEnd: boolean }
): { filters: FacetFilter[]; remaining: string } {
    const filters: FacetFilter[] = []
    const seen = new Set<string>()
    const quotedStart = openQuotedTokenStart(input)
    const remaining = input
        .slice(0, quotedStart)
        .replace(
            untilEnd ? TOKEN : TOKEN_FOLLOWED_BY_SPACE,
            (token: string, lead: string, minus: string, key: string, quoted?: string, bare?: string) => {
                const facet = findFacet(facets, key)
                const value = quoted !== undefined ? unescapeFacetValue(quoted) : bare
                if (!facet || value === undefined) {
                    return token
                }
                const filter = { facet: facet.key, value, negated: minus === '-' }
                const filterKey = facetFilterKey(filter)
                if (!seen.has(filterKey)) {
                    seen.add(filterKey)
                    filters.push(filter)
                }
                return lead
            }
        )
    const stillQuoting = input.slice(quotedStart)
    return { filters, remaining: `${remaining.replace(/\s{2,}/g, ' ')}${stillQuoting}`.replace(/^\s+/, '') }
}

export interface FacetDraft {
    facetKey: string
    negated: boolean
    partial: string
    /** The input before the draft token. It stays as the free text. */
    rest: string
}

export function parseFacetDraft(input: string, facets: FacetDefinitionBase[]): FacetDraft | null {
    const match = input.match(DRAFT_TOKEN)
    if (!match || match.index === undefined) {
        return null
    }
    const facet = findFacet(facets, match[3])
    if (!facet) {
        return null
    }
    return {
        facetKey: facet.key,
        negated: match[2] === '-',
        partial: match[4] !== undefined ? unescapeFacetValue(match[4]) : match[5],
        rest: input.slice(0, match.index + match[1].length),
    }
}

function serializeFacetValue(value: string): string {
    return !value || /[\s"]/.test(value) ? `"${value.replace(/[\\"]/g, (char) => `\\${char}`)}"` : value
}

/** One string for a URL search param: `-status:draft owner:"Jo Doe" renewal`. `parseFacetSearch` reads it back. */
export function serializeFacetSearch(value: FacetSearchValue): string {
    const tokens = value.filters.map(
        (filter) => `${filter.negated ? '-' : ''}${filter.facet}:${serializeFacetValue(filter.value)}`
    )
    return [...tokens, value.text.trim()].filter(Boolean).join(' ')
}

/** Reads `facet:value`, `-facet:value` and `facet:"quoted value"` into pills, and keeps everything else as the text. */
export function parseFacetSearch(query: string, facets: FacetDefinitionBase[]): FacetSearchValue {
    const { filters, remaining } = extractFacetFilters(query, facets, { untilEnd: true })
    return { filters, text: remaining.trim() }
}

export function toFacetQuery(value: FacetSearchValue): FacetQuery {
    const facets: FacetQuery['facets'] = {}
    for (const filter of value.filters) {
        const group = (facets[filter.facet] ??= { include: [], exclude: [] })
        const values = filter.negated ? group.exclude : group.include
        if (!values.includes(filter.value)) {
            values.push(filter.value)
        }
    }
    return { text: value.text.trim(), facets }
}

interface FacetFilterGroup<TRow> {
    facet: ClientFacet<TRow>
    positive: Set<string>
    negative: Set<string>
}

/** Groups the pills by facet once, so matching many rows doesn't regroup them per row. */
function groupFilters<TRow>(filters: FacetFilter[], facets: ClientFacet<TRow>[]): FacetFilterGroup<TRow>[] {
    const groups = new Map<string, FacetFilterGroup<TRow>>()
    for (const filter of filters) {
        const facet = findFacet(facets, filter.facet)
        if (!facet) {
            continue
        }
        const group = groups.get(facet.key) ?? { facet, positive: new Set(), negative: new Set() }
        ;(filter.negated ? group.negative : group.positive).add(filter.value.toLowerCase())
        groups.set(facet.key, group)
    }
    return [...groups.values()]
}

function passesGroups<TRow>(row: TRow, groups: FacetFilterGroup<TRow>[], skipFacet?: string): boolean {
    for (const { facet, positive, negative } of groups) {
        if (facet.key === skipFacet) {
            continue
        }
        const values = facet.getValues(row).map((value) => value.toLowerCase())
        if (positive.size && !values.some((value) => positive.has(value))) {
            return false
        }
        if (values.some((value) => negative.has(value))) {
            return false
        }
    }
    return true
}

/** Client mode: the rows the pills and the text let through. Pills on one facet are OR, facets are AND. */
export function filterFacetRows<TRow>(
    { rows, matchesText }: FacetSearchRows<TRow>,
    value: FacetSearchValue,
    facets: ClientFacet<TRow>[]
): TRow[] {
    const groups = groupFilters(value.filters, facets)
    const text = value.text.trim()
    return rows.filter((row) => passesGroups(row, groups) && (!text || matchesText(row, text)))
}

/**
 * Counts each facet's values over the rows the other pills and the text let through.
 * A facet's own pills are left out, so picking one value keeps the counts of its OR alternatives.
 */
export function createFacetCounter<TRow>(
    { rows, matchesText }: FacetSearchRows<TRow>,
    value: FacetSearchValue,
    facets: ClientFacet<TRow>[]
): (facetKey: string) => FacetValueOption[] {
    const text = value.text.trim()
    const textMatches = text ? rows.filter((row) => matchesText(row, text)) : rows
    const groups = groupFilters(value.filters, facets)
    return (facetKey) => {
        const facet = findFacet(facets, facetKey)
        if (!facet) {
            return []
        }
        const counts = new Map<string, { value: string; count: number }>()
        for (const row of textMatches) {
            if (!passesGroups(row, groups, facet.key)) {
                continue
            }
            const rowValues = new Map(facet.getValues(row).map((rowValue) => [rowValue.toLowerCase(), rowValue]))
            for (const [lowered, rowValue] of rowValues) {
                const entry = counts.get(lowered)
                if (entry) {
                    entry.count++
                } else {
                    counts.set(lowered, { value: rowValue, count: 1 })
                }
            }
        }
        return [...counts.values()].sort((a, b) => b.count - a.count || a.value.localeCompare(b.value))
    }
}
