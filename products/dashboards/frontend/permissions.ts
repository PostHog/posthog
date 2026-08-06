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

    // V1 collaborator privileges remain an additional restriction until those dashboards migrate to object-level RBAC.
    return (
        dashboard.access_control_version !== 'v1' ||
        (dashboard.effective_privilege_level ?? DashboardPrivilegeLevel.CanView) >= DashboardPrivilegeLevel.CanEdit
    )
}
