import { DashboardFilter, TileFilters } from '~/queries/schema/schema-general'

/** True when the filter carries no meaningful constraint (dashboard / tile override payloads). */
export function isDashboardFilterEmpty(filter: DashboardFilter | TileFilters | null | undefined): boolean {
    return (
        !filter ||
        (filter.date_from == null &&
            filter.date_to == null &&
            (filter.properties == null || (Array.isArray(filter.properties) && filter.properties.length === 0)) &&
            filter.breakdown_filter == null)
    )
}
