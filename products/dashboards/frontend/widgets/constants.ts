/** Shown on the widget tile when run_widgets fails or returns a per-tile error. */
export const DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE = 'Failed to load widget data.'

const WIDGET_FETCH_ERROR_PASSTHROUGH_PREFIXES = [
    'Tile not found',
    'You do not have access',
    'Unknown widget type:',
] as const

export function getDashboardWidgetFetchDisplayError(error: string | null | undefined): string | null {
    if (!error) {
        return null
    }

    if (WIDGET_FETCH_ERROR_PASSTHROUGH_PREFIXES.some((prefix) => error.startsWith(prefix))) {
        return error
    }

    return DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE
}
