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

interface FacetToken {
    negated: boolean
    key: string
    value: string
    quoted: boolean
}

/** One whitespace-separated piece of the input. A quote, plain or after `facet:`, holds its spaces and tokens. */
interface InputToken {
    start: number
    end: number
    /** A quote that the input ends inside. */
    open: boolean
    facet?: FacetToken
}

const FACET_PREFIX = /(-?)([\w-]+):/y

function isSpace(char: string): boolean {
    return /\s/.test(char)
}

function unescapeFacetValue(quoted: string): string {
    return quoted.replace(/\\([\s\S])/g, '$1')
}

/** The index after the closing quote, or -1 when the input ends inside the quote. */
function closingQuoteEnd(input: string, contentStart: number): number {
    let index = contentStart
    while (index < input.length) {
        if (input[index] === '"') {
            return index + 1
        }
        index += input[index] === '\\' ? 2 : 1
    }
    return -1
}

function wordEnd(input: string, start: number): number {
    let index = start
    while (index < input.length && !isSpace(input[index])) {
        index++
    }
    return index
}

function scanQuoted(input: string, start: number, contentStart: number, facet?: Omit<FacetToken, 'value'>): InputToken {
    const end = closingQuoteEnd(input, contentStart)
    const open = end < 0
    const contentEnd = open ? input.length : end - 1
    return {
        start,
        end: open ? input.length : end,
        open,
        facet: facet && { ...facet, value: unescapeFacetValue(input.slice(contentStart, contentEnd)) },
    }
}

function scanToken(input: string, start: number): InputToken {
    const atBoundary = start === 0 || isSpace(input[start - 1])
    if (!atBoundary) {
        return { start, end: wordEnd(input, start), open: false }
    }
    if (input[start] === '"') {
        return scanQuoted(input, start, start + 1)
    }
    FACET_PREFIX.lastIndex = start
    const prefix = FACET_PREFIX.exec(input)
    if (prefix) {
        const valueStart = FACET_PREFIX.lastIndex
        const facet = { negated: prefix[1] === '-', key: prefix[2] }
        if (input[valueStart] === '"') {
            return scanQuoted(input, start, valueStart + 1, { ...facet, quoted: true })
        }
        const end = wordEnd(input, valueStart)
        const value = input.slice(valueStart, end)
        if (!value.includes('"')) {
            return { start, end, open: false, facet: { ...facet, value, quoted: false } }
        }
    }
    return { start, end: wordEnd(input, start), open: false }
}

function scanTokens(input: string): InputToken[] {
    const tokens: InputToken[] = []
    let index = 0
    while (index < input.length) {
        if (isSpace(input[index])) {
            index++
            continue
        }
        const token = scanToken(input, index)
        tokens.push(token)
        index = token.end
    }
    return tokens
}

/** A quoted value is complete at its closing quote; a bare value once a space follows it, or at the end with `untilEnd`. */
function isComplete(token: InputToken, inputLength: number, untilEnd: boolean): boolean {
    if (!token.facet || token.open) {
        return false
    }
    return token.facet.quoted || (!!token.facet.value && (token.end < inputLength || untilEnd))
}

/**
 * Takes the complete, known `facet:value` tokens out of the input. Unknown facets and quoted phrases stay as typed.
 * With `untilEnd`, a token at the very end counts as complete; the bar leaves it as a draft until a space follows.
 */
export function extractFacetFilters(
    input: string,
    facets: FacetDefinitionBase[],
    { untilEnd }: { untilEnd: boolean }
): { filters: FacetFilter[]; remaining: string } {
    const filters: FacetFilter[] = []
    const seen = new Set<string>()
    const tokens = scanTokens(input)
    const openTail = tokens.at(-1)?.open ? tokens[tokens.length - 1].start : input.length
    let remaining = ''
    let cursor = 0
    for (const token of tokens) {
        const facet = token.facet && findFacet(facets, token.facet.key)
        if (!token.facet || !facet || !isComplete(token, input.length, untilEnd)) {
            continue
        }
        remaining += input.slice(cursor, token.start)
        cursor = token.end
        const filter = { facet: facet.key, value: token.facet.value, negated: token.facet.negated }
        if (!seen.has(facetFilterKey(filter))) {
            seen.add(facetFilterKey(filter))
            filters.push(filter)
        }
    }
    remaining += input.slice(cursor, openTail)
    return { filters, remaining: `${remaining.replace(/\s{2,}/g, ' ')}${input.slice(openTail)}`.replace(/^\s+/, '') }
}

export interface FacetDraft {
    facetKey: string
    negated: boolean
    partial: string
    /** The input before the draft token. It stays as the free text. */
    rest: string
}

export function parseFacetDraft(input: string, facets: FacetDefinitionBase[]): FacetDraft | null {
    const last = scanTokens(input).at(-1)
    const facet = last?.facet && last.end === input.length ? findFacet(facets, last.facet.key) : undefined
    if (!last?.facet || !facet) {
        return null
    }
    return {
        facetKey: facet.key,
        negated: last.facet.negated,
        partial: last.facet.value,
        rest: input.slice(0, last.start),
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

function passesGroups<TRow>(row: TRow, groups: FacetFilterGroup<TRow>[], orAlternativesOf?: string): boolean {
    for (const { facet, positive, negative } of groups) {
        const values = facet.getValues(row).map((value) => value.toLowerCase())
        if (facet.key !== orAlternativesOf && positive.size && !values.some((value) => positive.has(value))) {
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

export type FacetValueCounter = (facetKey: string, pill: { negated: boolean }) => FacetValueOption[]

/**
 * Counts each facet's values over the rows the pills and the text let through.
 * For a new pill the facet's own pills are left out, so picking one value keeps the counts of its OR alternatives.
 * Its negated pills stay, so a value it already excludes is not offered.
 * For a new negated pill every pill counts, so the count is the rows it would hide.
 */
export function createFacetCounter<TRow>(
    { rows, matchesText }: FacetSearchRows<TRow>,
    value: FacetSearchValue,
    facets: ClientFacet<TRow>[]
): FacetValueCounter {
    const text = value.text.trim()
    const textMatches = text ? rows.filter((row) => matchesText(row, text)) : rows
    const groups = groupFilters(value.filters, facets)
    return (facetKey, { negated }) => {
        const facet = findFacet(facets, facetKey)
        if (!facet) {
            return []
        }
        const orAlternativesOf = negated ? undefined : facet.key
        const counts = new Map<string, { value: string; count: number }>()
        for (const row of textMatches) {
            if (!passesGroups(row, groups, orAlternativesOf)) {
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
