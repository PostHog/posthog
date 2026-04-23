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

/** Keyword set for each `$event_type` autocapture emits. The set of `eventType` values must stay
 *  in sync with `eventTypeToVerb` in `lib/utils.tsx`; a test enforces this. Keywords are matched
 *  with `startsWith(query)` so each entry should only list terms that uniquely point at the
 *  interaction — avoid generic verbs like `input`, `drag`, `zoom`, `hold` that users might type
 *  for unrelated reasons. */
export const AUTOCAPTURE_INTERACTIONS: AutocaptureInteraction[] = [
    { label: 'Click', eventType: 'click', keywords: ['click', 'clicked', 'tap', 'tapped'] },
    { label: 'Change', eventType: 'change', keywords: ['change', 'changed', 'typed'] },
    { label: 'Submit', eventType: 'submit', keywords: ['submit', 'submitted', 'form'] },
    { label: 'Touch', eventType: 'touch', keywords: ['touch', 'touched'] },
    { label: 'Scroll', eventType: 'scroll', keywords: ['scroll', 'scrolled'] },
    { label: 'Toggle', eventType: 'toggle', keywords: ['toggle', 'toggled', 'switch', 'switched'] },
    { label: 'Swipe', eventType: 'swipe', keywords: ['swipe', 'swiped'] },
    { label: 'Long press', eventType: 'long_press', keywords: ['long press', 'longpress', 'press'] },
    { label: 'Pinch', eventType: 'pinch', keywords: ['pinch', 'pinched'] },
    { label: 'Pan', eventType: 'pan', keywords: ['pan', 'panned'] },
    { label: 'Rotation', eventType: 'rotation', keywords: ['rotation', 'rotate', 'rotated'] },
    { label: 'Value changed', eventType: 'value_changed', keywords: ['value changed', 'value change'] },
    { label: 'Menu action', eventType: 'menu_action', keywords: ['menu action', 'menu'] },
]

// Sanity check in tests: AUTOCAPTURE_INTERACTIONS eventTypes must match the keys of eventTypeToVerb.
export const _AUTOCAPTURE_INTERACTIONS_SOURCE = eventTypeToVerb

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
