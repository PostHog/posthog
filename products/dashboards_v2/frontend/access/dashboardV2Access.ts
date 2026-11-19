import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { DashboardEdit } from '../layout/dashboardEdits'

/**
 * Everything a person can do to a v2 dashboard, and the access level it needs. Each edit kind must appear here, so a
 * new edit does not type-check until someone decides who may make it. The logic refuses any edit, and the UI disables
 * any control, through `dashboardV2DisabledReason`, so there is one place to read and change the rules.
 */
export type DashboardV2Action = DashboardEdit['edit'] | 'undo' | 'redo'

export const DASHBOARD_V2_REQUIRED_LEVEL: Record<DashboardV2Action, AccessControlLevel> = {
    placeTiles: AccessControlLevel.Editor,
    moveTile: AccessControlLevel.Editor,
    addTile: AccessControlLevel.Editor,
    removeTile: AccessControlLevel.Editor,
    updateSection: AccessControlLevel.Editor,
    addTab: AccessControlLevel.Editor,
    renameTab: AccessControlLevel.Editor,
    removeTab: AccessControlLevel.Editor,
    undo: AccessControlLevel.Editor,
    redo: AccessControlLevel.Editor,
}

/**
 * Why the person may not take an action, or null when they may. `userAccessLevel` is the dashboard's own level, as v1
 * dashboards carry in `user_access_level`; without one it falls back to the project-wide dashboard level.
 */
export function dashboardV2DisabledReason(
    action: DashboardV2Action,
    userAccessLevel: AccessControlLevel | undefined
): string | null {
    return getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        DASHBOARD_V2_REQUIRED_LEVEL[action],
        userAccessLevel,
        false
    )
}
