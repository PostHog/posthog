import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

function getHigherProjectAccessLevel(
    currentLevel: AccessControlLevel,
    candidateLevel: AccessControlLevel
): AccessControlLevel {
    return accessLevelSatisfied(AccessControlResourceType.Project, candidateLevel, currentLevel)
        ? candidateLevel
        : currentLevel
}

export function getEffectiveProjectAccessForMember(params: {
    projectDefaultLevel: AccessControlLevel
    memberOverrideLevel: AccessControlLevel | null | undefined
    roleOverrideLevels: AccessControlLevel[]
    isOrganizationAdmin: boolean
}): {
    effectiveProjectLevel: AccessControlLevel
    hasAdminAccessViaRoles: boolean
} {
    if (params.isOrganizationAdmin) {
        return {
            effectiveProjectLevel: AccessControlLevel.Admin,
            hasAdminAccessViaRoles: false,
        }
    }

    const candidateLevels = [
        params.projectDefaultLevel,
        ...(params.memberOverrideLevel !== null && params.memberOverrideLevel !== undefined
            ? [params.memberOverrideLevel]
            : []),
        ...params.roleOverrideLevels,
    ]

    const effectiveProjectLevel = candidateLevels.reduce(getHigherProjectAccessLevel, params.projectDefaultLevel)

    return {
        effectiveProjectLevel,
        hasAdminAccessViaRoles: params.roleOverrideLevels.some((level) =>
            accessLevelSatisfied(AccessControlResourceType.Project, level, AccessControlLevel.Admin)
        ),
    }
}
