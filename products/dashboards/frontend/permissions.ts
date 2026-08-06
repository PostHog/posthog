import { DashboardPrivilegeLevel } from 'lib/constants'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, type DashboardBasicType } from '~/types'

export function canEditDashboard(
    dashboard: Pick<DashboardBasicType, 'access_control_version' | 'user_access_level' | 'effective_privilege_level'>
): boolean {
    // V1 dashboards use collaborator privileges until they are migrated to object-level RBAC.
    // Requiring both systems would deny valid V1 collaborators.
    if (dashboard.access_control_version === 'v1') {
        return (
            (dashboard.effective_privilege_level ?? DashboardPrivilegeLevel.CanView) >= DashboardPrivilegeLevel.CanEdit
        )
    }

    return accessLevelSatisfied(
        AccessControlResourceType.Dashboard,
        dashboard.user_access_level,
        AccessControlLevel.Editor
    )
}
