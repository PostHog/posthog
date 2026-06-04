import type { QuickFilter } from '~/types'

/** Event properties allowed in error tracking list widget `config.widgetFilters`. */
export const ERROR_TRACKING_WIDGET_FILTER_PROPERTY_NAMES = [
    '$environment',
    '$current_url',
    '$pathname',
    '$team',
    '$posthog_team',
    '$temporal_worker',
    '$temporal_worker_name',
] as const

export function isAllowedErrorTrackingWidgetFilter(filter: Pick<QuickFilter, 'property_name'>): boolean {
    const normalized = filter.property_name.trim().toLowerCase()
    return (ERROR_TRACKING_WIDGET_FILTER_PROPERTY_NAMES as readonly string[]).includes(normalized)
}
