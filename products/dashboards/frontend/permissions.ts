import { DashboardPrivilegeLevel } from 'lib/constants'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, type DashboardBasicType } from '~/types'

export function canEditDashboard(
    dashboard: Pick<DashboardBasicType, 'access_control_version' | 'user_access_level' | 'effective_privilege_level'>
): boolean {
    const rbacAllowsEditing = accessLevelSatisfied(
        AccessControlResourceType.Dashboard,
        dashboard.user_access_level,
        AccessControlLevel.Editor
    )

    if (!rbacAllowsEditing) {
        return false
    }

    // TODO(2026-08-06): migrate V1 collaborator dashboards to object-level RBAC, then drop this branch. Until then V1 collaborator privilege is an additional edit restriction on top of RBAC.
    return (
        dashboard.access_control_version !== 'v1' ||
        (dashboard.effective_privilege_level ?? DashboardPrivilegeLevel.CanView) >= DashboardPrivilegeLevel.CanEdit
    )
}
