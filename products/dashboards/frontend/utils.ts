import type { DashboardTile, QueryBasedInsightModel } from '~/types'

import { dashboardsPartialUpdate } from './generated/api'

export type WidgetFieldErrors = Record<string, string | undefined>

export class WidgetConfigValidationError extends Error {
    fieldErrors: WidgetFieldErrors

    constructor(fieldErrors: WidgetFieldErrors) {
        super('Widget config validation failed')
        this.name = 'WidgetConfigValidationError'
        this.fieldErrors = fieldErrors
    }
}

export function isWidgetConfigValidationError(error: unknown): error is WidgetConfigValidationError {
    return error instanceof WidgetConfigValidationError
}

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

export async function updateDashboardWidgetTile({
    teamId,
    dashboardId,
    tile,
    config,
    name,
    description,
}: {
    teamId: number
    dashboardId: number
    tile: DashboardTile<QueryBasedInsightModel>
    config?: Record<string, unknown>
    name?: string | null
    description?: string
}): Promise<DashboardTile<QueryBasedInsightModel>> {
    if (!tile.widget) {
        throw new Error('Tile has no widget')
    }

    const widgetPatch: Record<string, unknown> = {}
    if (config !== undefined) {
        widgetPatch.config = config
    }
    if (name !== undefined) {
        widgetPatch.name = name || null
    }
    if (description !== undefined) {
        widgetPatch.description = description
    }

    try {
        return await patchDashboardWidgetTile({ teamId, dashboardId, tile, widgetPatch })
    } catch (error) {
        if (config !== undefined) {
            const fieldErrors = parseWidgetConfigApiError(tile.widget.widget_type, error)
            if (fieldErrors && Object.keys(fieldErrors).length > 0) {
                throw new WidgetConfigValidationError(fieldErrors)
            }
        }
        throw error
    }
}
