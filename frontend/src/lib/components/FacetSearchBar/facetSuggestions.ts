import {
    ClientFacet,
    FacetDraft,
    FacetFilter,
    FacetSearchRows,
    FacetValueOption,
    LoadFacetValues,
    ServerFacet,
    createFacetCounter,
    facetFilterKey,
    findFacet,
    formatFacetValue,
} from './facetSearch'

const MAX_VALUE_SUGGESTIONS = 50
const MAX_CROSS_FACET_SUGGESTIONS = 8
const MIN_CROSS_FACET_TOKEN_LENGTH = 2

// The bar serves any row type. The typed `FacetSearchBar` props keep each caller consistent.
// oxlint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyFacet = ClientFacet<any> | ServerFacet

export type FacetValuesState =
    | { status: 'loaded'; options: FacetValueOption[] }
    | { status: 'loading' }
    | { status: 'error' }

export type FacetValueLoads = Record<string, FacetValuesState>

export interface FacetSuggestion {
    id: string
    kind: 'facet' | 'value' | 'search' | 'message'
    label: string
    detail?: string
    count?: number
    /** `facet` rows: the input after picking the facet. */
    nextInput?: string
    /** `value` rows: the pill to add. */
    filter?: FacetFilter
    /** `value` rows: the text typed before the value, kept as the search text. */
    rest?: string
}

type LoadedFacet = ServerFacet & { loadValues: LoadFacetValues }

export interface FacetValueRequest {
    facet: LoadedFacet
    search: string
}

export function valueLoadKey(facetKey: string, search: string): string {
    return `${facetKey}:${search.trim().toLowerCase()}`
}

export function isLoadedFacet(facet: AnyFacet): facet is LoadedFacet {
    return 'loadValues' in facet && !!facet.loadValues
}

interface SuggestionContext {
    facets: AnyFacet[]
    // oxlint-disable-next-line @typescript-eslint/no-explicit-any
    data: FacetSearchRows<any> | null
    filters: FacetFilter[]
    valueLoads: FacetValueLoads
}

type ListFacetValues = (facet: AnyFacet, text: string, search: string) => FacetValuesState

function createValueLister({ facets, data, filters, valueLoads }: SuggestionContext): ListFacetValues {
    const countersByText = new Map<string, (facetKey: string) => FacetValueOption[]>()
    return (facet, text, search) => {
        if (data && 'getValues' in facet) {
            const counter =
                countersByText.get(text) ??
                createFacetCounter(data, { filters, text }, facets as ClientFacet<unknown>[])
            countersByText.set(text, counter)
            return { status: 'loaded', options: counter(facet.key) }
        }
        if (isLoadedFacet(facet)) {
            return valueLoads[valueLoadKey(facet.key, search)] ?? { status: 'loading' }
        }
        return { status: 'loaded', options: ('values' in facet && facet.values) || [] }
    }
}

export function optionLabel(facet: AnyFacet, option: FacetValueOption): string {
    return option.label ?? formatFacetValue(facet, option.value)
}

function matchesPartial(facet: AnyFacet, option: FacetValueOption, partial: string): boolean {
    return (
        !partial ||
        optionLabel(facet, option).toLowerCase().includes(partial) ||
        option.value.toLowerCase().includes(partial)
    )
}

function splitLastToken(input: string): { rest: string; token: string } {
    const match = input.match(/^([\s\S]*?)(\S*)$/)
    return { rest: match?.[1] ?? '', token: match?.[2] ?? '' }
}

function message(id: string, label: string): FacetSuggestion[] {
    return [{ id, kind: 'message', label }]
}

function draftSuggestions(draft: FacetDraft, context: SuggestionContext, chosen: Set<string>): FacetSuggestion[] {
    const facet = findFacet(context.facets, draft.facetKey)!
    const state = createValueLister(context)(facet, draft.rest, draft.partial)
    if (state.status === 'loading') {
        return message('loading', 'Loading values…')
    }
    if (state.status === 'error') {
        return message('error', "Couldn't load values. Type again to retry.")
    }
    const partial = draft.partial.toLowerCase()
    const rows = state.options
        .filter(
            (option) => !chosen.has(facetFilterKey({ facet: facet.key, value: option.value, negated: draft.negated }))
        )
        .filter((option) => matchesPartial(facet, option, partial))
        .slice(0, MAX_VALUE_SUGGESTIONS)
        .map(
            (option): FacetSuggestion => ({
                id: `value-${facet.key}-${option.value}`,
                kind: 'value',
                label: `${draft.negated ? 'Not ' : ''}${optionLabel(facet, option)}`,
                detail: draft.negated && option.count !== undefined ? `Hides ${option.count}` : undefined,
                count: draft.negated ? undefined : option.count,
                filter: { facet: facet.key, value: option.value, negated: draft.negated },
                rest: draft.rest,
            })
        )
    if (rows.length) {
        return rows
    }
    return message('none', context.data ? 'No values match your other filters' : 'No values match')
}

function sortFacets(facets: AnyFacet[]): AnyFacet[] {
    return [...facets].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

function crossFacetValueSuggestions(
    token: { rest: string; bare: string; negated: boolean },
    context: SuggestionContext,
    chosen: Set<string>
): FacetSuggestion[] {
    const listValues = createValueLister(context)
    const matches: FacetSuggestion[] = []
    for (const facet of sortFacets(context.facets)) {
        const state = listValues(facet, token.rest, token.bare)
        if (state.status !== 'loaded') {
            continue
        }
        for (const option of state.options) {
            const filter = { facet: facet.key, value: option.value, negated: token.negated }
            if (!matchesPartial(facet, option, token.bare) || chosen.has(facetFilterKey(filter))) {
                continue
            }
            matches.push({
                id: `value-${facet.key}-${option.value}`,
                kind: 'value',
                label: `${token.negated ? 'Not ' : ''}${facet.label}: ${optionLabel(facet, option)}`,
                count: option.count,
                filter,
                rest: token.rest,
            })
        }
    }
    return matches.slice(0, MAX_CROSS_FACET_SUGGESTIONS)
}

export function buildSuggestions(
    input: string,
    draft: FacetDraft | null,
    context: SuggestionContext
): FacetSuggestion[] {
    const chosen = new Set(context.filters.map(facetFilterKey))
    if (draft) {
        return draftSuggestions(draft, context, chosen)
    }

    const ordered = sortFacets(context.facets)
    const { rest, token } = splitLastToken(input)
    if (!token) {
        return ordered
            .filter((facet) => facet.showOnFocus)
            .map((facet) => ({
                id: `facet-${facet.key}`,
                kind: 'facet',
                label: `${facet.key}:`,
                detail: facet.description,
                nextInput: `${input}${facet.key}:`,
            }))
    }

    const negated = token.startsWith('-')
    const bare = (negated ? token.slice(1) : token).toLowerCase()
    const result: FacetSuggestion[] = []
    if (bare) {
        for (const facet of ordered) {
            const names = [facet.key, facet.label.toLowerCase(), ...(facet.aliases ?? [])]
            if (names.some((name) => name.startsWith(bare))) {
                result.push({
                    id: `facet-${facet.key}`,
                    kind: 'facet',
                    label: `${negated ? '-' : ''}${facet.key}:`,
                    detail: facet.description,
                    nextInput: `${rest}${negated ? '-' : ''}${facet.key}:`,
                })
            }
        }
    }
    result.push({ id: 'search', kind: 'search', label: `Search for "${input.trim()}"` })
    if (bare.length >= MIN_CROSS_FACET_TOKEN_LENGTH) {
        result.push(...crossFacetValueSuggestions({ rest, bare, negated }, context, chosen))
    }
    return result
}

interface ValueRequestContext {
    input: string
    draft: FacetDraft | null
    open: boolean
    facets: AnyFacet[]
    filters: FacetFilter[]
    valueLabels: FacetValueLabels
    valueLoads: FacetValueLoads
}

function inputValueRequests(input: string, draft: FacetDraft | null, loaded: LoadedFacet[]): FacetValueRequest[] {
    if (draft) {
        const facet = loaded.find(({ key }) => key === draft.facetKey)
        return facet ? [{ facet, search: draft.partial }] : []
    }
    const token = splitLastToken(input).token.replace(/^-/, '')
    return token.length >= MIN_CROSS_FACET_TOKEN_LENGTH ? loaded.map((facet) => ({ facet, search: token })) : []
}

function pillLabelRequests(
    filters: FacetFilter[],
    loaded: LoadedFacet[],
    valueLabels: FacetValueLabels
): FacetValueRequest[] {
    return loaded
        .filter((facet) =>
            filters.some((filter) => filter.facet === facet.key && !valueLabels.has(labelKey(facet.key, filter.value)))
        )
        .map((facet) => ({ facet, search: '' }))
}

/** The loads the open suggestions and the pill labels need that have not started yet. Failed loads run again. */
export function pendingValueRequests({
    input,
    draft,
    open,
    facets,
    filters,
    valueLabels,
    valueLoads,
}: ValueRequestContext): FacetValueRequest[] {
    const loaded = facets.filter(isLoadedFacet)
    const requests = [
        ...(open ? inputValueRequests(input, draft, loaded) : []),
        ...pillLabelRequests(filters, loaded, valueLabels),
    ]
    const byLoadKey = new Map(requests.map((request) => [valueLoadKey(request.facet.key, request.search), request]))
    return [...byLoadKey]
        .filter(([loadKey]) => {
            const state = valueLoads[loadKey]
            return !state || state.status === 'error'
        })
        .map(([, request]) => request)
}

export type FacetValueLabels = Map<string, string>

function labelKey(facetKey: string, value: string): string {
    return `${facetKey}:${value}`
}

export function forgetValuesOf(valueLoads: FacetValueLoads, facetKeys: string[]): FacetValueLoads {
    return Object.fromEntries(
        Object.entries(valueLoads).filter(([loadKey]) => !facetKeys.some((key) => loadKey.startsWith(`${key}:`)))
    )
}

/** Facets whose loader changed between two renders. Their loaded values belong to the old loader. */
export function facetsWithNewLoaders(previous: AnyFacet[], next: AnyFacet[]): string[] {
    return next
        .filter(isLoadedFacet)
        .filter((facet) => {
            const before = findFacet(previous, facet.key)
            return !!before && isLoadedFacet(before) && before.loadValues !== facet.loadValues
        })
        .map((facet) => facet.key)
}

/** Labels of supplied and loaded values, so a pill reads `Team: Platform` rather than `Team: t-2`. */
export function labelsByFilterValue(facets: AnyFacet[], valueLoads: FacetValueLoads): FacetValueLabels {
    const labels: FacetValueLabels = new Map()
    const remember = (facet: AnyFacet, options: FacetValueOption[]): void => {
        for (const option of options) {
            labels.set(labelKey(facet.key, option.value), optionLabel(facet, option))
        }
    }
    for (const facet of facets) {
        if ('values' in facet && facet.values) {
            remember(facet, facet.values)
        }
        if (isLoadedFacet(facet)) {
            for (const [loadKey, state] of Object.entries(valueLoads)) {
                if (state.status === 'loaded' && loadKey.startsWith(`${facet.key}:`)) {
                    remember(facet, state.options)
                }
            }
        }
    }
    return labels
}

export function pillLabel(filter: FacetFilter, facets: AnyFacet[], valueLabels: FacetValueLabels): string {
    const facet = findFacet(facets, filter.facet)
    const valueLabel = valueLabels.get(labelKey(filter.facet, filter.value)) ?? formatFacetValue(facet, filter.value)
    return `${facet?.label ?? filter.facet}${filter.negated ? ' is not' : ''}: ${valueLabel}`
}
