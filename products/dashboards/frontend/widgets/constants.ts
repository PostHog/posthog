/** Shown on the widget tile when run_widgets fails or returns a per-tile error. */
export const DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE = 'Failed to load widget data.'

export const WIDGET_LIST_ORDER_DIRECTION_OPTIONS = [
    { value: 'DESC', label: 'Descending' },
    { value: 'ASC', label: 'Ascending' },
] as const

/** Debounce tile config PATCH → run_widgets refresh to avoid query storms while scrubbing filters. */
export const WIDGET_TILE_REFRESH_DEBOUNCE_MS = 500

/** Shown on widget tile filter controls when the viewer cannot edit the dashboard. */
export const DASHBOARD_WIDGET_TILE_FILTERS_READONLY_REASON =
    "You don't have edit permissions for this dashboard. Ask a dashboard collaborator with edit access to add you."

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

export type WidgetListCountNoun = {
    singular: string
    plural: string
}

export const WIDGET_LIST_COUNT_ISSUES: WidgetListCountNoun = { singular: 'issue', plural: 'issues' }
export const WIDGET_LIST_COUNT_RECORDINGS: WidgetListCountNoun = { singular: 'recording', plural: 'recordings' }

export function formatWidgetListCountFooter(
    shown: number,
    totalCount: number | undefined,
    totalCountCapped?: boolean,
    noun: WidgetListCountNoun = WIDGET_LIST_COUNT_ISSUES,
    hasMore?: boolean
): string {
    const label = shown === 1 && totalCount === 1 && !totalCountCapped ? noun.singular : noun.plural

    if (totalCount === undefined) {
        if (hasMore && shown > 0) {
            return `${shown}+ ${shown === 1 ? noun.singular : noun.plural}`
        }
        return `${shown} ${shown === 1 ? noun.singular : noun.plural}`
    }

    const totalLabel = totalCountCapped ? `${totalCount}+` : String(totalCount)
    return `${shown} of ${totalLabel} ${label}`
}
