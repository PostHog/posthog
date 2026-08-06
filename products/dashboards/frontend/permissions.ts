import { DashboardPrivilegeLevel } from 'lib/constants'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType, type DashboardBasicType } from '~/types'

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
    const dashboardAllowsEditing =
        (dashboard.effective_privilege_level ?? DashboardPrivilegeLevel.CanEdit) >= DashboardPrivilegeLevel.CanEdit

    return rbacAllowsEditing && dashboardAllowsEditing
}
