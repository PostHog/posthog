import type { QuickFilter } from '~/types'

/** Filter display names allowed on the error tracking list widget tile (case-insensitive). */
export const ERROR_TRACKING_WIDGET_FILTER_NAMES = ['team', 'environment', 'url path', 'temporal worker'] as const

export const ERROR_TRACKING_WIDGET_FILTER_DISPLAY_NAMES = [
    'Team',
    'Environment',
    'URL path',
    'Temporal worker',
] as const

/** Fallback when display names differ but the property matches Issues-tab conventions. */
export const ERROR_TRACKING_WIDGET_FILTER_PROPERTY_NAMES = [
    '$environment',
    '$current_url',
    '$pathname',
    '$team',
    '$posthog_team',
    '$temporal_worker',
    '$temporal_worker_name',
] as const

export function isAllowedErrorTrackingWidgetFilterName(name: string): boolean {
    const normalized = name.trim().toLowerCase()
    return (ERROR_TRACKING_WIDGET_FILTER_NAMES as readonly string[]).includes(normalized)
}

export function isAllowedErrorTrackingWidgetFilterPropertyName(propertyName: string): boolean {
    const normalized = propertyName.trim().toLowerCase()
    return (ERROR_TRACKING_WIDGET_FILTER_PROPERTY_NAMES as readonly string[]).includes(normalized)
}

export function isAllowedErrorTrackingWidgetFilter(filter: Pick<QuickFilter, 'name' | 'property_name'>): boolean {
    return (
        isAllowedErrorTrackingWidgetFilterName(filter.name) ||
        isAllowedErrorTrackingWidgetFilterPropertyName(filter.property_name)
    )
}

export { WIDGET_LIST_ORDER_DIRECTION_OPTIONS as ERROR_TRACKING_WIDGET_ORDER_DIRECTION_OPTIONS } from '../constants'
