import uniqBy from 'lodash.uniqby'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    ClientFacet,
    FacetDraft,
    FacetFilter,
    FacetSearchRows,
    FacetValueCounter,
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
    | { status: 'error'; reason?: string; retryable: boolean }

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
    return `${facetKey}:${search.trim()}`
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

interface ValueQuery {
    text: string
    search: string
    negated: boolean
}

type ListFacetValues = (facet: AnyFacet, query: ValueQuery) => FacetValuesState

function createValueLister({ facets, data, filters, valueLoads }: SuggestionContext): ListFacetValues {
    const countersByText = new Map<string, FacetValueCounter>()
    return (facet, { text, search, negated }) => {
        if (data && 'getValues' in facet) {
            const counter =
                countersByText.get(text) ??
                createFacetCounter(data, { filters, text }, facets as ClientFacet<unknown>[])
            countersByText.set(text, counter)
            return { status: 'loaded', options: counter(facet.key, { negated }) }
        }
        if (isLoadedFacet(facet)) {
            return valueLoads[valueLoadKey(facet.key, search)] ?? { status: 'loading' }
        }
        return { status: 'loaded', options: uniqBy(('values' in facet && facet.values) || [], 'value') }
    }
}

const EMPTY_VALUE_LABEL = '(empty string)'

function valueLabelOf(facet: AnyFacet | undefined, value: string, label?: string): string {
    return (label ?? formatFacetValue(facet, value)) || EMPTY_VALUE_LABEL
}

export function optionLabel(facet: AnyFacet, option: FacetValueOption): string {
    return valueLabelOf(facet, option.value, option.label)
}

function matchesPartial(facet: AnyFacet, option: FacetValueOption, partial: string): boolean {
    return (
        isLoadedFacet(facet) ||
        !partial ||
        optionLabel(facet, option).toLowerCase().includes(partial) ||
        option.value.toLowerCase().includes(partial)
    )
}

function splitLastToken(input: string): { rest: string; token: string } {
    let start = input.length
    while (start > 0 && !/\s/.test(input[start - 1])) {
        start--
    }
    return { rest: input.slice(0, start), token: input.slice(start) }
}

function message(id: string, label: string): FacetSuggestion[] {
    return [{ id, kind: 'message', label }]
}

type IsChosen = (filter: FacetFilter) => boolean

/** Client counts are counted under the current search, so a negated one is the rows it hides. A consumer's count is a plain total. */
function countOrHidden(
    option: FacetValueOption,
    negated: boolean,
    data: SuggestionContext['data']
): Pick<FacetSuggestion, 'count' | 'detail'> {
    if (!negated || !data) {
        return { count: option.count }
    }
    return { detail: option.count !== undefined ? `Hides ${humanFriendlyNumber(option.count)}` : undefined }
}

/** Rows match client facet values in any case, so two client pills that differ only by case are the same pill. */
export function pillIdentity(data: SuggestionContext['data']): (filter: FacetFilter) => string {
    return (filter) => facetFilterKey(data ? { ...filter, value: filter.value.toLowerCase() } : filter)
}

function chosenFilters({ data, filters }: SuggestionContext): IsChosen {
    const identity = pillIdentity(data)
    const chosen = new Set(filters.map(identity))
    return (filter) => chosen.has(identity(filter))
}

type FailedLoad = Extract<FacetValuesState, { status: 'error' }>

function becauseOf(reason: string | undefined): string {
    const because = reason?.trim().replace(/\.$/, '')
    return because ? `: ${because}` : ''
}

function loadFailedMessage({ reason, retryable }: FailedLoad, facetLabel?: string): string {
    const failure = `Couldn't load values${facetLabel ? ` for ${facetLabel}` : ''}${becauseOf(reason)}.`
    return retryable ? `${failure} Type again to retry.` : failure
}

function draftSuggestions(draft: FacetDraft, context: SuggestionContext, isChosen: IsChosen): FacetSuggestion[] {
    const facet = findFacet(context.facets, draft.facetKey)!
    const state = createValueLister(context)(facet, { text: draft.rest, search: draft.partial, negated: draft.negated })
    if (state.status === 'loading') {
        return message('loading', 'Loading values…')
    }
    if (state.status === 'error') {
        return message('error', loadFailedMessage(state))
    }
    const partial = draft.partial.toLowerCase()
    const filterOf = (option: FacetValueOption): FacetFilter => ({
        facet: facet.key,
        value: option.value,
        negated: draft.negated,
    })
    const unchosen = state.options.filter((option) => !isChosen(filterOf(option)))
    const rows = unchosen
        .filter((option) => matchesPartial(facet, option, partial))
        .slice(0, MAX_VALUE_SUGGESTIONS)
        .map(
            (option): FacetSuggestion => ({
                id: `value-${facetFilterKey(filterOf(option))}`,
                kind: 'value',
                label: `${draft.negated ? 'Not ' : ''}${optionLabel(facet, option)}`,
                ...countOrHidden(option, draft.negated, context.data),
                filter: filterOf(option),
                rest: draft.rest,
            })
        )
    if (rows.length) {
        return rows
    }
    const matching = state.options.filter((option) => matchesPartial(facet, option, partial))
    if (matching.length && matching.every((option) => isChosen(filterOf(option)))) {
        return message('none', partial ? 'Every matching value is already a filter' : 'Every value is already a filter')
    }
    const hasOtherFilters = context.filters.some((filter) => filter.facet !== facet.key) || !!draft.rest.trim()
    if (context.data && !state.options.length && hasOtherFilters) {
        return message('none', 'No values match your other filters')
    }
    return message('none', partial ? 'No values match' : 'This filter has no values')
}

function sortFacets(facets: AnyFacet[]): AnyFacet[] {
    return [...facets].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

function crossFacetValueSuggestions(
    token: { rest: string; search: string; bare: string; negated: boolean },
    context: SuggestionContext,
    isChosen: IsChosen
): FacetSuggestion[] {
    const listValues = createValueLister(context)
    const matches: FacetSuggestion[] = []
    const unfinished: UnfinishedLoad[] = []
    for (const facet of sortFacets(context.facets)) {
        const state = listValues(facet, { text: token.rest, search: token.search, negated: token.negated })
        if (state.status !== 'loaded') {
            unfinished.push({ facet, state })
            continue
        }
        for (const option of state.options) {
            const filter = { facet: facet.key, value: option.value, negated: token.negated }
            if (!matchesPartial(facet, option, token.bare) || isChosen(filter)) {
                continue
            }
            matches.push({
                id: `value-${facetFilterKey(filter)}`,
                kind: 'value',
                label: `${token.negated ? 'Not ' : ''}${facet.label}: ${optionLabel(facet, option)}`,
                ...countOrHidden(option, token.negated, context.data),
                filter,
                rest: token.rest,
            })
        }
    }
    return [...matches.slice(0, MAX_CROSS_FACET_SUGGESTIONS), ...unfinishedLoadMessage(unfinished)]
}

interface UnfinishedLoad {
    facet: AnyFacet
    state: Exclude<FacetValuesState, { status: 'loaded' }>
}

function unfinishedLoadMessage(loads: UnfinishedLoad[]): FacetSuggestion[] {
    if (loads.some(({ state }) => state.status === 'loading')) {
        return message('loading', 'Loading values…')
    }
    const failed = loads.find(({ state }) => state.status === 'error')
    return failed?.state.status === 'error' ? message('error', loadFailedMessage(failed.state, failed.facet.label)) : []
}

export function buildSuggestions(
    input: string,
    draft: FacetDraft | null,
    context: SuggestionContext
): FacetSuggestion[] {
    const isChosen = chosenFilters(context)
    if (draft) {
        return draftSuggestions(draft, context, isChosen)
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
    const search = negated ? token.slice(1) : token
    const bare = search.toLowerCase()
    const namedByToken = (facet: AnyFacet): boolean =>
        [facet.key, facet.label.toLowerCase(), ...(facet.aliases ?? [])].some((name) => name.startsWith(bare))
    // A lone `-` starts an exclusion, so it lists the facets the empty input lists.
    const offeredFacets = ordered.filter(bare ? namedByToken : (facet) => facet.showOnFocus)
    const result: FacetSuggestion[] = offeredFacets.map((facet) => ({
        id: `facet-${facet.key}`,
        kind: 'facet',
        label: `${negated ? '-' : ''}${facet.key}:`,
        detail: facet.description,
        nextInput: `${rest}${negated ? '-' : ''}${facet.key}:`,
    }))
    result.push({ id: 'search', kind: 'search', label: `Search for "${input.trim()}"` })
    if (bare.length >= MIN_CROSS_FACET_TOKEN_LENGTH) {
        result.push(...crossFacetValueSuggestions({ rest, search, bare, negated }, context, isChosen))
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

/** The loads the open suggestions and the pill labels need that have not started yet. A failed load runs again only for what the person types. */
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
    const statusOf = (request: FacetValueRequest): FacetValuesState['status'] | undefined =>
        valueLoads[valueLoadKey(request.facet.key, request.search)]?.status
    const unstarted = (request: FacetValueRequest): boolean => !statusOf(request)
    const unstartedOrFailed = (request: FacetValueRequest): boolean =>
        !statusOf(request) || statusOf(request) === 'error'
    const requests = [
        ...(open ? inputValueRequests(input, draft, loaded) : []).filter(unstartedOrFailed),
        ...pillLabelRequests(filters, loaded, valueLabels).filter(unstarted),
    ]
    return uniqBy(requests, (request) => valueLoadKey(request.facet.key, request.search))
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

/** Facets whose loader is new since the last render. Values cached under their key belong to an earlier loader. */
export function facetsWithNewLoaders(previous: AnyFacet[], next: AnyFacet[]): string[] {
    return next
        .filter(isLoadedFacet)
        .filter((facet) => {
            const before = findFacet(previous, facet.key)
            return !before || !isLoadedFacet(before) || before.loadValues !== facet.loadValues
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

/** `loading` and `failed`: the pill shows the raw value until its facet's `loadValues('')` gives the label. */
export type PillLabelStatus = 'shown' | 'loading' | 'failed'

export interface FacetPill {
    filter: FacetFilter
    label: string
    labelStatus: PillLabelStatus
    /** Why the pill shows the raw value, for its tooltip and screen readers. Empty once the label shows. */
    labelNote: string
}

function pillLabelState(
    filter: FacetFilter,
    facet: AnyFacet | undefined,
    context: PillContext
): Pick<FacetPill, 'labelStatus' | 'labelNote'> {
    if (!facet || !isLoadedFacet(facet) || context.valueLabels.has(labelKey(filter.facet, filter.value))) {
        return { labelStatus: 'shown', labelNote: '' }
    }
    const load = context.valueLoads[valueLoadKey(facet.key, '')]
    if (load?.status === 'error') {
        return { labelStatus: 'failed', labelNote: ` (couldn't load the label${becauseOf(load.reason)})` }
    }
    return load?.status === 'loaded'
        ? { labelStatus: 'shown', labelNote: '' }
        : { labelStatus: 'loading', labelNote: ' (loading the label)' }
}

interface PillContext {
    facets: AnyFacet[]
    valueLoads: FacetValueLoads
    valueLabels: FacetValueLabels
}

export function describePills(filters: FacetFilter[], context: PillContext): FacetPill[] {
    return filters.map((filter) => {
        const facet = findFacet(context.facets, filter.facet)
        const valueLabel = valueLabelOf(
            facet,
            filter.value,
            context.valueLabels.get(labelKey(filter.facet, filter.value))
        )
        return {
            filter,
            label: `${facet?.label ?? filter.facet}${filter.negated ? ' is not' : ''}: ${valueLabel}`,
            ...pillLabelState(filter, facet, context),
        }
    })
}
