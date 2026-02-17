import { orderedAccessLevels } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

const PROJECT_ACCESS_LEVEL_ORDER = orderedAccessLevels(AccessControlResourceType.Project)

function getProjectAccessLevelIndex(level: AccessControlLevel): number {
    const index = PROJECT_ACCESS_LEVEL_ORDER.indexOf(level)
    return index === -1 ? 0 : index
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

    const effectiveProjectLevel = candidateLevels.reduce((currentHighest, candidateLevel) => {
        return getProjectAccessLevelIndex(candidateLevel) > getProjectAccessLevelIndex(currentHighest)
            ? candidateLevel
            : currentHighest
    }, params.projectDefaultLevel)

    return {
        effectiveProjectLevel,
        hasAdminAccessViaRoles: params.roleOverrideLevels.includes(AccessControlLevel.Admin),
    }
}
