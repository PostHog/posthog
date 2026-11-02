import { DashboardTileBasicType } from '~/types'

/**
 * Soft-deleted tiles do not count, because the backend does not count them either. Session responses omit
 * the deprecated insight `dashboards` field, and a PATCH of it replaces the whole membership, so a writer
 * builds the new list from this one.
 */
export function liveDashboardIds(tiles: DashboardTileBasicType[] | null | undefined): number[] {
    return (tiles || []).filter((tile) => !tile.deleted).map((tile) => tile.dashboard_id)
}
