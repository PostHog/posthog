import type { CrossProjectDashboardFilters } from './crossProjectDashboardLogic'

const KEYS: (keyof CrossProjectDashboardFilters)[] = ['date_from', 'date_to', 'interval']

/** The tile's own keys win over the dashboard's, so a tile that overrides only its dates keeps the dashboard's interval. */
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
