import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { Setting } from '~/scenes/settings/types'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

/**
 * Whether a user's per-resource access levels satisfy a setting's `accessControl` gate.
 * Kept apart from settingsLogic so it stays a pure function that's cheap to test — the
 * caller passes in `resource_access_control` from the app context.
 */
export const matchesSettingAccessControl = (
    accessControl: Pick<Setting, 'accessControl'>['accessControl'],
    resourceAccessControl: Partial<Record<AccessControlResourceType, AccessControlLevel>> | undefined
): boolean => {
    if (!accessControl) {
        return true
    }
    const userAccessLevel = resourceAccessControl?.[accessControl.resourceType]
    if (!userAccessLevel) {
        return false
    }
    return accessLevelSatisfied(accessControl.resourceType, userAccessLevel, accessControl.minimumAccessLevel)
}
