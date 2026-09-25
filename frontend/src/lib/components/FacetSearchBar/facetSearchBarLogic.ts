import { MakeLogicType, actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'

import {
    FacetDefinition,
    FacetFilter,
    FacetSearchValue,
    MatchesText,
    createFacetCounter,
    facetFilterKey,
    findFacet,
    formatFacetValue,
    sortFacets,
} from './facetQuery'

const MAX_VALUE_SUGGESTIONS = 50
const MAX_CROSS_FACET_SUGGESTIONS = 8
const MIN_CROSS_FACET_TOKEN_LENGTH = 2

// The logic serves any item type. The typed `FacetSearchBar` component keeps callers consistent.
/* oxlint-disable @typescript-eslint/no-explicit-any */
export interface FacetSearchBarLogicProps {
    id: string
    facets: FacetDefinition<any>[]
    items: any[]
    value: FacetSearchValue
    onChange: (value: FacetSearchValue) => void
    matchesText: MatchesText<any>
}
/* oxlint-enable @typescript-eslint/no-explicit-any */

type FacetSuggestionKind = 'facet' | 'value' | 'search' | 'none'

export interface FacetSuggestion {
    id: string
    kind: FacetSuggestionKind
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

export interface FacetDraft {
    facetKey: string
    facetLabel: string
    negated: boolean
    partial: string
    /** The input before the draft token. It stays as the free text. */
    rest: string
}

const DRAFT_PATTERN = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"?|(\S*))$/
// A token is complete when whitespace follows it, or when its quoted value is closed.
const COMPLETE_TOKEN = /(^|\s)(-?)([\w-]+):(?:"((?:[^"\\]|\\.)*)"|([^\s"]+)(?=\s))/g

/** Takes every complete, known `facet:value` token out of the input. The rest stays as typed. */
function extractCompleteFilters(
    input: string,
    facets: FacetDefinition<unknown>[]
): { filters: FacetFilter[]; remaining: string } {
    const filters: FacetFilter[] = []
    const remaining = input.replace(
        COMPLETE_TOKEN,
        (token: string, lead: string, minus: string, key: string, quoted?: string, bare?: string) => {
            const facet = findFacet(facets, key)
            const value = quoted !== undefined ? quoted.replace(/\\(.)/g, '$1') : bare
            if (!facet || !value) {
                return token
            }
            filters.push({ facet: facet.key, value, negated: minus === '-' })
            return lead
        }
    )
    return { filters, remaining: remaining.replace(/\s{2,}/g, ' ').replace(/^\s+/, '') }
}

function parseFacetDraft(input: string, facets: FacetDefinition<unknown>[]): FacetDraft | null {
    const match = input.match(DRAFT_PATTERN)
    if (!match || match.index === undefined) {
        return null
    }
    const facet = findFacet(facets, match[3])
    if (!facet) {
        return null
    }
    return {
        facetKey: facet.key,
        facetLabel: facet.label,
        negated: match[2] === '-',
        partial: match[4] !== undefined ? match[4].replace(/\\(.)/g, '$1') : match[5],
        rest: input.slice(0, match.index + match[1].length),
    }
}

function splitLastToken(input: string): { rest: string; token: string } {
    const match = input.match(/^([\s\S]*?)(\S*)$/)
    return { rest: match?.[1] ?? '', token: match?.[2] ?? '' }
}

function textOf(input: string, draft: FacetDraft | null): string {
    return (draft ? draft.rest : input).trim()
}

const isFilterRow = (suggestion: FacetSuggestion | null | undefined): boolean =>
    suggestion?.kind === 'facet' || suggestion?.kind === 'value'

const verbOf = (suggestion: FacetSuggestion): string =>
    suggestion.kind === 'facet' ? `pick ${suggestion.label}` : 'add filter'

function buildSuggestions(
    input: string,
    draft: FacetDraft | null,
    { facets, items, value, matchesText }: Pick<FacetSearchBarLogicProps, 'facets' | 'items' | 'value' | 'matchesText'>
): FacetSuggestion[] {
    const chosen = new Set(value.filters.map(facetFilterKey))

    if (draft) {
        const facet = findFacet(facets, draft.facetKey)!
        const partial = draft.partial.toLowerCase()
        const counts = createFacetCounter(
            items,
            { filters: value.filters, text: draft.rest },
            facets,
            matchesText
        )(facet.key)
        const rows = counts
            .filter(
                ({ value: v }) => !chosen.has(facetFilterKey({ facet: facet.key, value: v, negated: draft.negated }))
            )
            .filter(({ value: v }) => {
                const label = formatFacetValue(facet, v).toLowerCase()
                return !partial || label.includes(partial) || v.toLowerCase().includes(partial)
            })
            .slice(0, MAX_VALUE_SUGGESTIONS)
            .map(
                ({ value: v, count }): FacetSuggestion => ({
                    id: `value-${facet.key}-${v}`,
                    kind: 'value',
                    label: `${draft.negated ? 'Not ' : ''}${formatFacetValue(facet, v)}`,
                    detail: draft.negated ? `Hides ${count}` : undefined,
                    count: draft.negated ? undefined : count,
                    filter: { facet: facet.key, value: v, negated: draft.negated },
                    rest: draft.rest,
                })
            )
        return rows.length ? rows : [{ id: 'none', kind: 'none', label: 'No values match your other filters' }]
    }

    const ordered = sortFacets(facets)
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
        const matches: FacetSuggestion[] = []
        const countValues = createFacetCounter(items, { filters: value.filters, text: rest }, facets, matchesText)
        for (const facet of ordered) {
            for (const { value: v, count } of countValues(facet.key)) {
                const label = formatFacetValue(facet, v)
                if (!label.toLowerCase().includes(bare) && !v.toLowerCase().includes(bare)) {
                    continue
                }
                const filter = { facet: facet.key, value: v, negated }
                if (chosen.has(facetFilterKey(filter))) {
                    continue
                }
                matches.push({
                    id: `value-${facet.key}-${v}`,
                    kind: 'value',
                    label: `${negated ? 'Not ' : ''}${facet.label}: ${label}`,
                    count,
                    filter,
                    rest,
                })
            }
        }
        result.push(...matches.slice(0, MAX_CROSS_FACET_SUGGESTIONS))
    }
    return result
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicValues {
    draft: FacetDraft | null
    highlightedIndex: number
    highlightedSuggestion: FacetSuggestion | null
    hints: string[]
    input: string
    open: boolean
    rawHighlightedIndex: number
    suggestions: FacetSuggestion[]
    tabTarget: FacetSuggestion | null
    title: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicActions {
    applyHighlighted: () => {
        value: true
    }
    applySuggestion: (suggestion: FacetSuggestion) => {
        suggestion: FacetSuggestion
    }
    applyTabTarget: () => {
        value: true
    }
    moveHighlight: (delta: number) => {
        delta: number
    }
    removeFilter: (filter: FacetFilter) => {
        filter: FacetFilter
    }
    removeLastFilter: () => {
        value: true
    }
    setHighlightedIndex: (index: number) => {
        index: number
    }
    setInput: (input: string) => {
        input: string
    }
    setOpen: (open: boolean) => {
        open: boolean
    }
    syncInput: (input: string) => {
        input: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface facetSearchBarLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        draft: (input: any, facets: FacetDefinition<any>[]) => FacetDraft | null
        suggestions: (
            input: any,
            draft: FacetDraft | null,
            facets: FacetDefinition<any>[],
            items: any[],
            value: FacetSearchValue,
            matchesText: MatchesText<any>
        ) => FacetSuggestion[]
        highlightedIndex: (rawHighlightedIndex: number, suggestions: FacetSuggestion[]) => number
        highlightedSuggestion: (suggestions: FacetSuggestion[], highlightedIndex: number) => FacetSuggestion | null
        tabTarget: (
            input: any,
            suggestions: FacetSuggestion[],
            highlightedSuggestion: FacetSuggestion | null
        ) => FacetSuggestion | null
        title: (input: any, draft: FacetDraft | null) => string
        hints: (highlightedSuggestion: FacetSuggestion | null, tabTarget: FacetSuggestion | null) => string[]
    }
}

export type facetSearchBarLogicType = MakeLogicType<
    facetSearchBarLogicValues,
    facetSearchBarLogicActions,
    FacetSearchBarLogicProps,
    facetSearchBarLogicMeta
>

export const facetSearchBarLogic = kea<facetSearchBarLogicType>([
    props({} as FacetSearchBarLogicProps),
    key((props) => props.id),
    path((key) => ['lib', 'components', 'FacetSearchBar', 'facetSearchBarLogic', key]),
    actions({
        setInput: (input: string) => ({ input }),
        syncInput: (input: string) => ({ input }),
        setOpen: (open: boolean) => ({ open }),
        setHighlightedIndex: (index: number) => ({ index }),
        moveHighlight: (delta: number) => ({ delta }),
        applySuggestion: (suggestion: FacetSuggestion) => ({ suggestion }),
        applyHighlighted: true,
        applyTabTarget: true,
        removeFilter: (filter: FacetFilter) => ({ filter }),
        removeLastFilter: true,
    }),
    reducers(({ props }) => ({
        input: [
            (props.value?.text ?? '') as string,
            {
                setInput: (_, { input }) => input,
                syncInput: (_, { input }) => input,
            },
        ],
        open: [
            false,
            {
                setOpen: (_, { open }) => open,
                setInput: () => true,
            },
        ],
        rawHighlightedIndex: [
            0,
            {
                setHighlightedIndex: (_, { index }) => index,
                setInput: () => 0,
                syncInput: () => 0,
                setOpen: () => 0,
            },
        ],
    })),
    selectors({
        draft: [
            (s, p) => [s.input, p.facets],
            (input: string, facets: FacetDefinition<unknown>[]): FacetDraft | null => parseFacetDraft(input, facets),
        ],
        suggestions: [
            (s, p) => [s.input, s.draft, p.facets, p.items, p.value, p.matchesText],
            (
                input,
                draft: FacetDraft | null,
                facets: FacetDefinition<any>[],
                items: any[],
                value: FacetSearchValue,
                matchesText: MatchesText<any>
            ): FacetSuggestion[] => buildSuggestions(input, draft, { facets, items, value, matchesText }),
        ],
        highlightedIndex: [
            (s) => [s.rawHighlightedIndex, s.suggestions],
            (raw: number, suggestions: FacetSuggestion[]): number => Math.max(0, Math.min(raw, suggestions.length - 1)),
        ],
        highlightedSuggestion: [
            (s) => [s.suggestions, s.highlightedIndex],
            (suggestions: FacetSuggestion[], index: number): FacetSuggestion | null =>
                suggestions[index]?.kind === 'none' ? null : (suggestions[index] ?? null),
        ],
        tabTarget: [
            (s) => [s.input, s.suggestions, s.highlightedSuggestion],
            (
                input: string,
                suggestions: FacetSuggestion[],
                highlighted: FacetSuggestion | null
            ): FacetSuggestion | null => {
                // Tab and → never run a plain search. With an empty input, Tab moves focus as usual.
                if (!input.trim()) {
                    return null
                }
                return isFilterRow(highlighted) ? highlighted : (suggestions.find(isFilterRow) ?? null)
            },
        ],
        title: [
            (s) => [s.input, s.draft],
            (input: string, draft: FacetDraft | null): string =>
                draft
                    ? `${draft.facetLabel}${draft.negated ? ' is not' : ''}`
                    : input.trim()
                      ? 'Search or filter'
                      : 'Filter by',
        ],
        hints: [
            (s) => [s.highlightedSuggestion, s.tabTarget],
            (highlighted: FacetSuggestion | null, tabTarget: FacetSuggestion | null): string[] => {
                const hints: string[] = []
                if (highlighted?.kind === 'search') {
                    hints.push('Enter to search')
                } else if (highlighted && isFilterRow(highlighted)) {
                    hints.push(`Enter${tabTarget === highlighted ? ' or Tab' : ''} to ${verbOf(highlighted)}`)
                }
                if (tabTarget && tabTarget !== highlighted) {
                    hints.push(`Tab or → to ${verbOf(tabTarget)}`)
                }
                return [...hints, '↑↓ to move', 'Esc to close']
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        setInput: ({ input }) => {
            // Typed or pasted `facet:value` tokens become pills as soon as they are complete.
            const { filters, remaining } = extractCompleteFilters(input, props.facets)
            const known = new Set(props.value.filters.map(facetFilterKey))
            const added = filters.filter((filter) => !known.has(facetFilterKey(filter)))
            const nextInput = filters.length ? remaining : input
            const text = textOf(nextInput, parseFacetDraft(nextInput, props.facets))
            if (filters.length) {
                actions.syncInput(nextInput)
            }
            if (added.length || text !== props.value.text) {
                props.onChange({ filters: [...props.value.filters, ...added], text })
            }
        },
        moveHighlight: ({ delta }) => {
            const last = Math.max(0, values.suggestions.length - 1)
            actions.setHighlightedIndex(Math.max(0, Math.min(values.highlightedIndex + delta, last)))
        },
        applySuggestion: ({ suggestion }) => {
            if (suggestion.kind === 'facet' && suggestion.nextInput !== undefined) {
                actions.setInput(suggestion.nextInput)
            } else if (suggestion.kind === 'value' && suggestion.filter) {
                const rest = (suggestion.rest ?? '').trimEnd()
                props.onChange({ filters: [...props.value.filters, suggestion.filter], text: rest.trim() })
                actions.syncInput(rest ? `${rest} ` : '')
                actions.setOpen(true)
            } else {
                actions.setOpen(false)
            }
        },
        applyHighlighted: () => {
            if (values.highlightedSuggestion) {
                actions.applySuggestion(values.highlightedSuggestion)
            }
        },
        applyTabTarget: () => {
            if (values.tabTarget) {
                actions.applySuggestion(values.tabTarget)
            }
        },
        removeFilter: ({ filter }) => {
            const removed = facetFilterKey(filter)
            props.onChange({
                filters: props.value.filters.filter((f) => facetFilterKey(f) !== removed),
                text: props.value.text,
            })
        },
        removeLastFilter: () => {
            if (props.value.filters.length) {
                props.onChange({ filters: props.value.filters.slice(0, -1), text: props.value.text })
            }
        },
    })),
    propsChanged(({ actions, values, props }) => {
        // The URL or a "Clear filters" button can change the text without this input.
        if (props.value.text !== textOf(values.input, values.draft)) {
            actions.syncInput(props.value.text)
        }
    }),
])
