import api, { ApiConfig, ApiMethodOptions } from 'lib/api'
import { liveDashboardIds } from 'scenes/dashboard/liveDashboardIds'

import { DashboardFilter, HogQLVariable, RefreshType, TileFilters } from '~/queries/schema/schema-general'
import { DashboardTileBasicType, InsightShortId, InsightModel } from '~/types'

import { dashboardsAddInsightCreate, dashboardsDeleteTile } from 'products/dashboards/frontend/generated/api'

async function _perform(
    method: 'create' | 'update',
    insight: Partial<InsightModel>,
    id?: number,
    options?: ApiMethodOptions
): Promise<InsightModel> {
    return method === 'create' ? api.insights[method](insight) : api.insights[method](id!, insight, options)
}

export const insightsApi = {
    _perform,
    async getByShortId(
        shortId: InsightShortId,
        basic?: boolean,
        refresh?: RefreshType,
        filtersOverride?: DashboardFilter | null,
        variablesOverride?: Record<string, HogQLVariable> | null,
        tileFiltersOverride?: TileFilters | null
    ): Promise<InsightModel | null> {
        const legacyInsights = await api.insights.loadInsight(
            shortId,
            basic,
            refresh,
            filtersOverride,
            variablesOverride,
            tileFiltersOverride
        )
        if (legacyInsights.results.length === 0) {
            return null
        }
        return legacyInsights.results[0] as InsightModel
    },
    async getByNumericId(numericId: number): Promise<InsightModel | null> {
        const legacyInsight = await api.insights.get(numericId)
        if (legacyInsight === null) {
            return null
        }
        return legacyInsight
    },
    /** Creates the insight, then places it on each of `dashboardIds` in order. */
    async create(insight: Partial<InsightModel>, dashboardIds: number[] = []): Promise<InsightModel> {
        const created = await this._perform('create', insight)
        if (!dashboardIds.length) {
            return created
        }
        const tiles = await this.addNewInsightToDashboards(created.id, dashboardIds)
        return { ...created, dashboard_tiles: [...(created.dashboard_tiles || []), ...tiles] }
    },
    async update(id: number, insightUpdate: Partial<InsightModel>, options?: ApiMethodOptions): Promise<InsightModel> {
        return this._perform('update', insightUpdate, id, options)
    },
    async duplicate(insight: InsightModel): Promise<InsightModel> {
        const {
            id,
            short_id,
            result,
            created_at,
            created_by,
            last_modified_at,
            last_modified_by,
            dashboards,
            dashboard_tiles,
            ...rest
        } = insight
        // The copy goes on every dashboard the original sits on.
        return this.create(
            { ...rest, name: insight.name ? `${insight.name} (copy)` : insight.name },
            liveDashboardIds(dashboard_tiles)
        )
    },
    /** Places a saved insight on a dashboard. A removed tile comes back with its old layout. */
    async addToDashboard(insightId: number, dashboardId: number): Promise<DashboardTileBasicType> {
        const tile = await dashboardsAddInsightCreate(String(ApiConfig.getCurrentTeamId()), dashboardId, {
            insight_id: insightId,
        })
        return { id: tile.id, dashboard_id: tile.dashboard_id }
    },
    /**
     * Places an insight created a moment ago on these dashboards. A refusal deletes the insight again and
     * rethrows, because a create that names a dashboard the user may not use must leave no insight behind.
     */
    async addNewInsightToDashboards(insightId: number, dashboardIds: number[]): Promise<DashboardTileBasicType[]> {
        const tiles: DashboardTileBasicType[] = []
        try {
            for (const dashboardId of dashboardIds) {
                tiles.push(await this.addToDashboard(insightId, dashboardId))
            }
        } catch (error) {
            await this._perform('update', { deleted: true }, insightId).catch(() => undefined)
            throw error
        }
        return tiles
    },
    /** Takes the insight off a dashboard. The insight itself stays. */
    async removeFromDashboard(insight: Pick<InsightModel, 'dashboard_tiles'>, dashboardId: number): Promise<void> {
        const tile = insight.dashboard_tiles?.find((tile) => tile.dashboard_id === dashboardId && !tile.deleted)
        if (!tile) {
            return
        }
        await dashboardsDeleteTile(String(ApiConfig.getCurrentTeamId()), dashboardId, { tile_id: tile.id })
    },
}
