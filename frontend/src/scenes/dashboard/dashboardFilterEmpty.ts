import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'

/** True when the filter carries no meaningful constraint (dashboard / tile override payloads). */
export function isDashboardFilterEmpty(filter: DashboardFilter | TileFilters | null | undefined): boolean {
    return (
        !filter ||
        (isFilterValueEmpty(filter.date_from) &&
            isFilterValueEmpty(filter.date_to) &&
            isFilterValueEmpty(filter.properties) &&
            isFilterValueEmpty(filter.breakdown_filter) &&
            isFilterValueEmpty(filter.interval) &&
            isFilterValueEmpty(filter.filterTestAccounts) &&
            !(filter as TileFilters).ignoreDashboardFilters)
    )
}

const OVERRIDABLE_KEYS = [
    'date_from',
    'date_to',
    'properties',
    'breakdown_filter',
    'interval',
    'filterTestAccounts',
] as const satisfies readonly (keyof DashboardFilter)[]

function isFilterValueEmpty(value: unknown): boolean {
    return value == null || (Array.isArray(value) && value.length === 0)
}

function clearedFilterKeys(filter: DashboardFilter | null | undefined): (keyof DashboardFilter)[] {
    if (!filter) {
        return []
    }
    return OVERRIDABLE_KEYS.filter((key) => key in filter && isFilterValueEmpty(filter[key]))
}

/**
 * True when the override switches a filter off — the `{"date_from": null}` that "no date range override"
 * produces, rather than a payload that just doesn't mention dates. Both read as empty to
 * `isDashboardFilterEmpty`, but only this one changes what the dashboard shows, so it has to survive
 * being written to the URL and passed on.
 */
export function clearsDashboardFilter(filter: DashboardFilter | null | undefined): boolean {
    return clearedFilterKeys(filter).length > 0
}

/** As `clearsDashboardFilter`, but only counts filters the dashboard has actually saved. */
export function clearsSavedDashboardFilter(
    filter: DashboardFilter | null | undefined,
    savedFilters: DashboardFilter | null | undefined
): boolean {
    if (!savedFilters) {
        return false
    }
    return clearedFilterKeys(filter).some((key) => !isFilterValueEmpty(savedFilters[key]))
}
