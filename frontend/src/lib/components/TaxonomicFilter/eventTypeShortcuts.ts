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

/** Extra keywords a user might type for each `$event_type`. Purely additive — the list always
 *  includes the eventType itself and its derived label, so entries here are synonyms for better
 *  discovery (e.g. typing `form` matches `submit`). Omit an eventType to fall back to just
 *  eventType + derived label. */
const KEYWORD_SYNONYMS: Record<string, string[]> = {
    click: ['clicked', 'tap', 'tapped'],
    change: ['changed', 'typed'],
    submit: ['submitted', 'form'],
    touch: ['touched'],
    scroll: ['scrolled'],
    toggle: ['toggled', 'switch', 'switched'],
    swipe: ['swiped'],
    long_press: ['long press', 'press'],
    pinch: ['pinched'],
    pan: ['panned'],
    rotation: ['rotate', 'rotated'],
    value_changed: ['value change', 'value changed'],
    menu_action: ['menu', 'menu action'],
}

function formatLabel(eventType: string): string {
    const spaced = eventType.replace(/_/g, ' ')
    return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function buildKeywords(eventType: string): string[] {
    const label = formatLabel(eventType).toLowerCase()
    return [...new Set([eventType, label, ...(KEYWORD_SYNONYMS[eventType] ?? [])])]
}

/** Interactions derived from the canonical `eventTypeToVerb` map in `lib/utils.tsx`. Adding a new
 *  `$event_type` to that map automatically surfaces it here with a sensible default label and
 *  matching keywords (eventType + label). Extra user-facing synonyms live in `KEYWORD_SYNONYMS`. */
export const AUTOCAPTURE_INTERACTIONS: AutocaptureInteraction[] = Object.keys(eventTypeToVerb).map((eventType) => ({
    eventType,
    label: formatLabel(eventType),
    keywords: buildKeywords(eventType),
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
