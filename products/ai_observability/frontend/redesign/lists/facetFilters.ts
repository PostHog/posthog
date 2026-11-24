import { escapeRegex } from 'lib/utils/actions'

import { AnyPropertyFilter, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export type FacetKey = 'model' | 'provider' | 'tool' | 'errors' | 'slow'

export const ALL_FACETS: readonly FacetKey[] = ['model', 'provider', 'tool', 'errors', 'slow']

export interface FacetState {
    models: string[]
    providers: string[]
    tools: string[]
    errorsOnly: boolean
    slow: boolean
}

export interface FacetOptions {
    models: string[]
    providers: string[]
    tools: string[]
    /** The p95 latency of generations, in seconds, which the slow facet filters above. */
    slowThresholdSeconds: number | null
}

// pinned: the facets are plain property filters in the shared `filters` URL param, so saved links keep working
const MODEL_KEY = '$ai_model'
const PROVIDER_KEY = '$ai_provider'
const TOOLS_KEY = '$ai_tools_called'
const ERROR_KEY = '$ai_is_error'
const LATENCY_KEY = '$ai_latency'

const TOOLS_REGEX = /^\(\^\|,\)\((.+)\)\(,\|\$\)$/

function isEventFilter(filter: AnyPropertyFilter, key: string, operator: PropertyOperator): boolean {
    return filter.type === PropertyFilterType.Event && filter.key === key && filter.operator === operator
}

function listValue(value: unknown): string[] {
    return (Array.isArray(value) ? value : value === undefined || value === null ? [] : [value]).map(String)
}

function toolsFromRegex(value: unknown): string[] {
    const match = typeof value === 'string' ? TOOLS_REGEX.exec(value) : null
    if (!match) {
        return []
    }
    return match[1].split(/(?<!\\)\|/).map((tool) => tool.replace(/\\(.)/g, '$1'))
}

function facetOf(filter: AnyPropertyFilter): FacetKey | null {
    if (isEventFilter(filter, MODEL_KEY, PropertyOperator.Exact)) {
        return 'model'
    }
    if (isEventFilter(filter, PROVIDER_KEY, PropertyOperator.Exact)) {
        return 'provider'
    }
    if (isEventFilter(filter, TOOLS_KEY, PropertyOperator.Regex) && toolsFromRegex(filter.value).length > 0) {
        return 'tool'
    }
    if (isEventFilter(filter, ERROR_KEY, PropertyOperator.Exact) && String(filter.value) === 'true') {
        return 'errors'
    }
    if (isEventFilter(filter, LATENCY_KEY, PropertyOperator.GreaterThan)) {
        return 'slow'
    }
    return null
}

export function readFacets(filters: AnyPropertyFilter[]): FacetState {
    const state: FacetState = { models: [], providers: [], tools: [], errorsOnly: false, slow: false }
    for (const filter of filters) {
        const facet = facetOf(filter)
        const value = 'value' in filter ? filter.value : undefined
        if (facet === 'model') {
            state.models = listValue(value)
        } else if (facet === 'provider') {
            state.providers = listValue(value)
        } else if (facet === 'tool') {
            state.tools = toolsFromRegex(value)
        } else if (facet === 'errors') {
            state.errorsOnly = true
        } else if (facet === 'slow') {
            state.slow = true
        }
    }
    return state
}

/** The filters the facets don't own, which the generic property filter pills show. */
export function nonFacetFilters(filters: AnyPropertyFilter[]): AnyPropertyFilter[] {
    return filters.filter((filter) => facetOf(filter) === null)
}

function eventFilter(
    key: string,
    operator: PropertyOperator,
    value: EventPropertyFilter['value']
): EventPropertyFilter {
    return { type: PropertyFilterType.Event, key, operator, value }
}

export function withFacets(
    filters: AnyPropertyFilter[],
    change: Partial<FacetState>,
    slowThresholdSeconds: number | null
): AnyPropertyFilter[] {
    const next = { ...readFacets(filters), ...change }
    // A slow filter keeps the threshold it was made with, so a shared link reads the same list.
    const keptSlow = filters.find((filter) => facetOf(filter) === 'slow')
    const slow = !next.slow
        ? []
        : keptSlow
          ? [keptSlow]
          : slowThresholdSeconds !== null
            ? [eventFilter(LATENCY_KEY, PropertyOperator.GreaterThan, slowThresholdSeconds)]
            : []
    return [
        ...(next.models.length ? [eventFilter(MODEL_KEY, PropertyOperator.Exact, next.models)] : []),
        ...(next.providers.length ? [eventFilter(PROVIDER_KEY, PropertyOperator.Exact, next.providers)] : []),
        ...(next.tools.length
            ? [eventFilter(TOOLS_KEY, PropertyOperator.Regex, `(^|,)(${next.tools.map(escapeRegex).join('|')})(,|$)`)]
            : []),
        ...(next.errorsOnly ? [eventFilter(ERROR_KEY, PropertyOperator.Exact, 'true')] : []),
        ...slow,
        ...nonFacetFilters(filters),
    ]
}

/** Replaces the filters the pills own, keeping the facet filters. */
export function withNonFacetFilters(filters: AnyPropertyFilter[], pills: AnyPropertyFilter[]): AnyPropertyFilter[] {
    return [...filters.filter((filter) => facetOf(filter) !== null), ...pills]
}
