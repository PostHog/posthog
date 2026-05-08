import { eventTypeToVerb } from 'lib/utils'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { QuickFilterItem } from './types'

export interface AutocaptureInteraction {
    label: string
    eventType: string
    keywords: string[]
}

/** Maximum number of distinct interactions a query can match before we suppress shortcuts. A
 *  single-character query like `s` matches submit / scroll / swipe / toggle-via-switch; showing
 *  all four would drown real results. Once the query narrows to this many or fewer distinct
 *  interactions (as the user keeps typing), we surface them. */
export const MAX_SHORTCUT_MATCHES = 3

/** Tokens shorter than this are skipped when deriving keywords from verbs (drops filler words
 *  like "a", "in" which would flood matches on common letters). */
const MIN_KEYWORD_TOKEN_LENGTH = 3

function formatLabel(eventType: string): string {
    const spaced = eventType.replace(/_/g, ' ')
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Keywords for an interaction are derived from the canonical sources: the `$event_type` key
 *  itself, its display label, and the user-facing verb in `eventTypeToVerb` (both as a whole
 *  phrase and split into word tokens). No hand-maintained synonym list — any new entry added
 *  to `eventTypeToVerb` automatically gets sensible search terms. */
function deriveKeywords(eventType: string): string[] {
    const label = formatLabel(eventType).toLowerCase()
    const verb = eventTypeToVerb[eventType].toLowerCase()
    const verbTokens = verb.split(/\s+/).filter((token) => token.length >= MIN_KEYWORD_TOKEN_LENGTH)
    return [...new Set([eventType, label, verb, ...verbTokens])]
}

/** Interactions derived from the canonical `eventTypeToVerb` map in `lib/utils.tsx`. Adding a new
 *  `$event_type` there automatically surfaces a shortcut with sensible keywords. */
export const AUTOCAPTURE_INTERACTIONS: AutocaptureInteraction[] = Object.keys(eventTypeToVerb).map((eventType) => ({
    eventType,
    label: formatLabel(eventType),
    keywords: deriveKeywords(eventType),
}))

function matchesKeyword(interaction: AutocaptureInteraction, trimmedQuery: string): boolean {
    return interaction.keywords.some((keyword) => keyword.startsWith(trimmedQuery))
}

function matchingInteractions(searchQuery: string): AutocaptureInteraction[] {
    const query = searchQuery.trim().toLowerCase()
    if (!query) {
        return []
    }
    const matches = AUTOCAPTURE_INTERACTIONS.filter((interaction) => matchesKeyword(interaction, query))
    // If the query is still too ambiguous (matches many interactions), suppress shortcuts rather
    // than flood the results. Once the user types another character or two the set narrows
    // naturally and the shortcuts reappear.
    return matches.length <= MAX_SHORTCUT_MATCHES ? matches : []
}

/** Shortcuts for event-series pickers: selecting one adds an `$autocapture` series with a
 *  `$event_type` property filter attached in one step. */
export function buildAutocaptureSeriesShortcuts(searchQuery: string): QuickFilterItem[] {
    return matchingInteractions(searchQuery).map(({ label, eventType }) => ({
        _type: 'quick_filter',
        name: `${label} (autocapture)`,
        filterValue: eventType,
        operator: PropertyOperator.Exact,
        propertyKey: '$event_type',
        propertyFilterType: PropertyFilterType.Event,
        eventName: '$autocapture',
    }))
}

/** Shortcuts for property-filter pickers: selecting one adds just the `$event_type` property
 *  filter (no event series). */
export function buildEventTypeFilterShortcuts(searchQuery: string): QuickFilterItem[] {
    return matchingInteractions(searchQuery).map(({ label, eventType }) => ({
        _type: 'quick_filter',
        name: `${label} (event type)`,
        filterValue: eventType,
        operator: PropertyOperator.Exact,
        propertyKey: '$event_type',
        propertyFilterType: PropertyFilterType.Event,
    }))
}
