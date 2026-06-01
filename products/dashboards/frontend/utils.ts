import type { DashboardTile, QueryBasedInsightModel } from '~/types'

import { dashboardsPartialUpdate } from './generated/api'
import { WidgetConfigValidationError, type WidgetFieldErrors } from './widget_types/widgetConfigValidation'

function parseWidgetConfigApiError(_widgetType: string, _error: unknown): WidgetFieldErrors | null {
    return null
}

async function patchDashboardWidgetTile({
    teamId,
    dashboardId,
    tile,
    widgetPatch,
}: {
    teamId: number
    dashboardId: number
    tile: DashboardTile<QueryBasedInsightModel>
    widgetPatch: Record<string, unknown>
}): Promise<DashboardTile<QueryBasedInsightModel>> {
    const dashboard = await dashboardsPartialUpdate(String(teamId), dashboardId, {
        tiles: [
            {
                id: tile.id,
                widget: {
                    id: tile.widget!.id,
                    ...widgetPatch,
                },
            },
        ],
    })
    const updatedTile = dashboard.tiles?.find((existingTile) => existingTile.id === tile.id)
    if (!updatedTile) {
        throw new Error('Updated tile not found in dashboard response')
    }
    return updatedTile as DashboardTile<QueryBasedInsightModel>
}

export async function updateDashboardWidgetTileConfig({
    teamId,
    dashboardId,
    tile,
    config,
}: {
    teamId: number
    dashboardId: number
    tile: DashboardTile<QueryBasedInsightModel>
    config: Record<string, unknown>
}): Promise<DashboardTile<QueryBasedInsightModel>> {
    if (!tile.widget) {
        throw new Error('Tile has no widget')
    }

    try {
        return await patchDashboardWidgetTile({ teamId, dashboardId, tile, widgetPatch: { config } })
    } catch (error) {
        const fieldErrors = parseWidgetConfigApiError(tile.widget.widget_type, error)
        if (fieldErrors && Object.keys(fieldErrors).length > 0) {
            throw new WidgetConfigValidationError(fieldErrors)
        }
        throw error
    }
}

export async function updateDashboardWidgetTileMetadata({
    teamId,
    dashboardId,
    tile,
    name,
    description,
}: {
    teamId: number
    dashboardId: number
    tile: DashboardTile<QueryBasedInsightModel>
    name?: string | null
    description?: string
}): Promise<DashboardTile<QueryBasedInsightModel>> {
    if (!tile.widget) {
        throw new Error('Tile has no widget')
    }

    const payload: { name?: string | null; description?: string } = {}
    if (name !== undefined) {
        payload.name = name || null
    }
    if (description !== undefined) {
        payload.description = description
    }

    return patchDashboardWidgetTile({ teamId, dashboardId, tile, widgetPatch: payload })
}
