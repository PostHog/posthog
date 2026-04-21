import { PropertyFilterType, PropertyOperator } from '~/types'

import { QuickFilterItem } from './types'

export interface AutocaptureInteraction {
    label: string
    eventType: string
    keywords: string[]
}

export const AUTOCAPTURE_INTERACTIONS: AutocaptureInteraction[] = [
    { label: 'Click', eventType: 'click', keywords: ['click', 'clicked', 'tap', 'tapped'] },
    { label: 'Change', eventType: 'change', keywords: ['change', 'changed', 'input', 'typed'] },
    { label: 'Submit', eventType: 'submit', keywords: ['submit', 'submitted', 'form'] },
    { label: 'Touch', eventType: 'touch', keywords: ['touch', 'touched'] },
    { label: 'Scroll', eventType: 'scroll', keywords: ['scroll', 'scrolled'] },
    { label: 'Toggle', eventType: 'toggle', keywords: ['toggle', 'toggled', 'switch'] },
    { label: 'Swipe', eventType: 'swipe', keywords: ['swipe', 'swiped'] },
    { label: 'Long press', eventType: 'long_press', keywords: ['long press', 'longpress', 'press', 'hold'] },
    { label: 'Pinch', eventType: 'pinch', keywords: ['pinch', 'pinched', 'zoom'] },
    { label: 'Pan', eventType: 'pan', keywords: ['pan', 'panned', 'drag'] },
    { label: 'Rotation', eventType: 'rotation', keywords: ['rotation', 'rotate', 'rotated'] },
    { label: 'Value changed', eventType: 'value_changed', keywords: ['value changed', 'value', 'edit', 'edited'] },
    { label: 'Menu action', eventType: 'menu_action', keywords: ['menu action', 'menu'] },
]

function matchesKeyword(interaction: AutocaptureInteraction, trimmedQuery: string): boolean {
    return interaction.keywords.some((keyword) => keyword.startsWith(trimmedQuery))
}

export function buildEventTypeShortcuts({
    searchQuery,
    includeEventName,
}: {
    searchQuery: string
    includeEventName: boolean
}): QuickFilterItem[] {
    const query = searchQuery.trim().toLowerCase()
    if (!query) {
        return []
    }

    return AUTOCAPTURE_INTERACTIONS.filter((interaction) => matchesKeyword(interaction, query)).map(
        ({ label, eventType }) => ({
            _type: 'quick_filter',
            name: includeEventName ? `${label} (autocapture)` : `${label} (event type)`,
            filterValue: eventType,
            operator: PropertyOperator.Exact,
            propertyKey: '$event_type',
            propertyFilterType: PropertyFilterType.Event,
            ...(includeEventName ? { eventName: '$autocapture' } : {}),
        })
    )
}
