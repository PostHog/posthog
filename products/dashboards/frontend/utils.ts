import { DashboardPrivilegeLevel } from 'lib/constants'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import {
    AccessControlLevel,
    AccessControlResourceType,
    type DashboardBasicType,
    type DashboardTile,
    type QueryBasedInsightModel,
} from '~/types'

import { dashboardsPartialUpdate } from './generated/api'
import type { PatchedPatchedDashboardOpenApiApi } from './generated/api.schemas'
import { parseDashboardWidgetConfigApiError } from './widgets/registry'

export type WidgetFieldErrors = Record<string, string | undefined>

/**
 * Whether the current user can edit a dashboard, mirroring the backend's write-path enforcement.
 *
 * The backend requires BOTH the RBAC access level (AccessControlPermission -> `user_access_level`) and the
 * legacy collaboration restriction (CanEditDashboard -> `effective_privilege_level`) to pass. Gating the edit
 * UI on RBAC alone opened editors the API then rejected on save, so users lost unsaved work on legacy-restricted
 * dashboards. Checking both here keeps the UI honest about what the API will accept.
 */
export function canEditDashboard(
    dashboard: Pick<DashboardBasicType, 'user_access_level' | 'effective_privilege_level'>
): boolean {
    const rbacAllowsEditing = dashboard.user_access_level
        ? accessLevelSatisfied(
              AccessControlResourceType.Dashboard,
              dashboard.user_access_level,
              AccessControlLevel.Editor
          )
        : false

    // A missing effective_privilege_level (e.g. an older/partial payload) must not silently add a restriction,
    // so treat it as CanEdit and let RBAC be the deciding factor in that case.
    const legacyAllowsEditing =
        (dashboard.effective_privilege_level ?? DashboardPrivilegeLevel.CanEdit) >= DashboardPrivilegeLevel.CanEdit

    return rbacAllowsEditing && legacyAllowsEditing
}

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

export async function updateDashboardWidgetTile({
    teamId,
    dashboardId,
    tile,
    config,
    name,
    description,
    showDescription,
}: {
    teamId: number
    dashboardId: number
    tile: DashboardTile<QueryBasedInsightModel>
    config?: Record<string, unknown>
    name?: string | null
    description?: string
    showDescription?: boolean
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

    const tilePatch: Record<string, unknown> = {
        id: tile.id,
    }
    if (showDescription !== undefined) {
        tilePatch.show_description = showDescription
    }
    if (Object.keys(widgetPatch).length > 0) {
        tilePatch.widget = {
            id: tile.widget.id,
            ...widgetPatch,
        }
    }

    try {
        const dashboard = await dashboardsPartialUpdate(String(teamId), dashboardId, {
            tiles: [tilePatch],
        } as PatchedPatchedDashboardOpenApiApi)
        const updatedTile = dashboard.tiles?.find((existingTile) => existingTile.id === tile.id)
        if (!updatedTile) {
            throw new Error('Updated tile not found in dashboard response')
        }
        return updatedTile as unknown as DashboardTile<QueryBasedInsightModel>
    } catch (error) {
        if (config !== undefined) {
            const fieldErrors = parseDashboardWidgetConfigApiError(tile.widget.widget_type, error, config)
            if (fieldErrors && Object.keys(fieldErrors).length > 0) {
                throw new WidgetConfigValidationError(fieldErrors)
            }
        }
        throw error
    }
}
