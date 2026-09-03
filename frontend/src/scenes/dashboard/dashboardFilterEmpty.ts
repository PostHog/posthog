import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'

/** True when the filter does not override a saved dashboard or tile filter. */
export function isDashboardFilterEmpty(filter: DashboardFilter | TileFilters | null | undefined): boolean {
    return (
        !filter ||
        (filter.date_from === undefined &&
            filter.date_to === undefined &&
            filter.properties === undefined &&
            filter.breakdown_filter === undefined &&
            filter.interval === undefined &&
            filter.filterTestAccounts === undefined &&
            !(filter as TileFilters).ignoreDashboardFilters)
    )
}
