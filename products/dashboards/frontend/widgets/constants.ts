/** Shown on the widget tile when run_widgets fails or returns a per-tile error. */
export const DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE = 'Failed to load widget data.'

export const WIDGET_LIST_ORDER_DIRECTION_OPTIONS = [
    { value: 'DESC', label: 'Descending' },
    { value: 'ASC', label: 'Ascending' },
] as const

/** Shown on widget tile filter controls when the viewer cannot edit the dashboard. */
export const DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON =
    "You don't have edit permissions for this dashboard. Ask a dashboard collaborator with edit access to add you."

/** Debounce before PATCHing tile config after on-tile filter edits (run_widgets refresh). */
export const WIDGET_TILE_REFRESH_DEBOUNCE_MS = 300

const WIDGET_FETCH_ERROR_PASSTHROUGH_PREFIXES = [
    'Tile not found',
    'You do not have access',
    'Unknown widget type:',
] as const

/** `isUserFacing` comes from the run result's `error_is_user_facing`: the backend wrote the message for the viewer. */
export function getDashboardWidgetFetchDisplayError(
    error: string | null | undefined,
    isUserFacing?: boolean | null
): string | null {
    if (!error) {
        return null
    }

    if (isUserFacing || WIDGET_FETCH_ERROR_PASSTHROUGH_PREFIXES.some((prefix) => error.startsWith(prefix))) {
        return error
    }

    return DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE
}
