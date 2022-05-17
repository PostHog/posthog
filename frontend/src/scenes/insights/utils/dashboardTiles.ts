import { DashboardTile, InsightModel } from '~/types'

export function mergeWithDashboardTile<T extends InsightModel | Partial<InsightModel>>(
    insight: T,
    tile: DashboardTile
): T {
    const updatedTarget = { ...insight }

    updatedTarget.result = tile.result || []
    updatedTarget.layouts = tile.layouts || {}
    updatedTarget.color = tile.color || null
    updatedTarget.last_refresh = tile.last_refresh || null
    updatedTarget.filters = tile.filters
    updatedTarget.filters_hash = tile.filters_hash || ''

    return updatedTarget
}
