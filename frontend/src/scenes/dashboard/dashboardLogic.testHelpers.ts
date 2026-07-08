import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import { DashboardFilter } from '~/queries/schema/schema-general'
import { DashboardTile, DashboardType, QueryBasedInsightModel } from '~/types'

import _dashboardJson from './__mocks__/dashboard.json'

const dashboardJson = getQueryBasedDashboard(_dashboardJson as any as DashboardType)!

export function insightOnDashboard(
    insightId: number,
    dashboardsRelation: number[],
    insight: Partial<QueryBasedInsightModel> = {}
): QueryBasedInsightModel {
    const tiles = dashboardJson.tiles.filter((tile) => !!tile.insight && tile.insight?.id === insightId)
    let tile = dashboardJson.tiles[0]
    if (tiles.length) {
        tile = tiles[0]
    }
    if (!tile.insight) {
        throw new Error('tile has no insight')
    }
    return {
        ...tile.insight,
        dashboards: dashboardsRelation,
        dashboard_tiles: dashboardsRelation.map((dashboardId) => ({ id: insight.id!, dashboard_id: dashboardId })),
        query: { ...tile.insight.query, ...insight.query, kind: (tile.insight.query?.kind || insight.query?.kind)! },
    }
}

let tileId = 0
export const tileFromInsight = (
    insight: QueryBasedInsightModel,
    id: number = tileId++
): DashboardTile<QueryBasedInsightModel> => ({
    id: id,
    layouts: {},
    color: null,
    insight: insight,
})

export const dashboardResult = (
    dashboardId: number,
    tiles: DashboardTile<QueryBasedInsightModel>[],
    filters: Partial<DashboardFilter> = {}
): DashboardType<QueryBasedInsightModel> => {
    return {
        ...dashboardJson,
        filters: { ...dashboardJson.filters, ...filters },
        id: dashboardId,
        tiles,
    }
}
