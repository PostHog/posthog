import type { CrossProjectDashboardFilters } from './crossProjectDashboardLogic'

const KEYS: (keyof CrossProjectDashboardFilters)[] = ['date_from', 'date_to', 'interval']

/**
 * Resolve what one tile asks its project for.
 *
 * The dashboard's filters apply first and the tile's own keys win over them, so a tile that
 * overrides only its date range still follows the dashboard's interval.
 */
export function mergeTileFilters(
    dashboardFilters?: CrossProjectDashboardFilters,
    tileFilters?: CrossProjectDashboardFilters
): CrossProjectDashboardFilters {
    const filters: CrossProjectDashboardFilters = { ...dashboardFilters }
    for (const key of KEYS) {
        const value = tileFilters?.[key]
        if (value !== undefined && value !== null) {
            filters[key] = value as never
        }
    }
    return filters
}
