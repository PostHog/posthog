import { DashboardTileBasicType } from '~/types'

/**
 * Soft-deleted tiles do not count, because the backend does not count them either. Session responses omit
 * the deprecated insight `dashboards` field, so this is the list of dashboards an insight sits on.
 */
export function liveDashboardIds(tiles: DashboardTileBasicType[] | null | undefined): number[] {
    return (tiles || []).filter((tile) => !tile.deleted).map((tile) => tile.dashboard_id)
}
