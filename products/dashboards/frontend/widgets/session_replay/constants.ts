import type { QuickFilter } from '~/types'

/** Event property keys allowed on session replay list widget `widgetFilters`. */
export const SESSION_REPLAY_WIDGET_FILTER_PROPERTY_NAMES = [
    '$browser',
    '$os',
    '$device_type',
    '$geoip_country_code',
    '$geoip_city_name',
    '$current_url',
    '$pathname',
    '$host',
    '$referring_domain',
    '$lib',
    '$environment',
] as const

export function isAllowedSessionReplayWidgetFilterPropertyName(propertyName: string): boolean {
    const normalized = propertyName.trim().toLowerCase()
    return (SESSION_REPLAY_WIDGET_FILTER_PROPERTY_NAMES as readonly string[]).includes(normalized)
}

export function isAllowedSessionReplayWidgetFilter(filter: Pick<QuickFilter, 'property_name'>): boolean {
    return isAllowedSessionReplayWidgetFilterPropertyName(filter.property_name)
}
