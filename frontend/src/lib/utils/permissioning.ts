import {
    EitherMemberType,
    ExplicitTeamMemberType,
    OrganizationMemberType,
    UserType,
    OrganizationBasicType,
} from '../../types'
import { EitherMembershipLevel, OrganizationMembershipLevel, TeamMembershipLevel } from '../constants'

/** If access level change is disallowed given the circumstances, returns a reason why so. Otherwise returns null. */
export function getReasonForAccessLevelChangeProhibition(
    currentMembershipLevel: OrganizationMembershipLevel | null,
    currentUser: UserType,
    memberToBeUpdated: EitherMemberType,
    newLevelOrAllowedLevels: EitherMembershipLevel | EitherMembershipLevel[]
): null | string {
    if (memberToBeUpdated.user.uuid === currentUser.uuid) {
        return "You can't change your own access level."
    }
    if (!currentMembershipLevel) {
        return 'Your membership level is unknown.'
    }
    let effectiveLevelToBeUpdated: OrganizationMembershipLevel
    if ('effectiveLevel' in (memberToBeUpdated as ExplicitTeamMemberType)) {
        // In EitherMemberType only ExplicitTeamMemberType has effectiveLevel
        effectiveLevelToBeUpdated = (memberToBeUpdated as ExplicitTeamMemberType).effective_level
    } else {
        effectiveLevelToBeUpdated = (memberToBeUpdated as OrganizationMemberType).level
    }
    if (Array.isArray(newLevelOrAllowedLevels)) {
        if (currentMembershipLevel === OrganizationMembershipLevel.Owner) {
            return null
        }
        if (!newLevelOrAllowedLevels.length) {
            return "You don't have permission to change this member's access level."
        }
    } else {
        if (newLevelOrAllowedLevels === effectiveLevelToBeUpdated) {
            return "It doesn't make sense to set the same level as before."
        }
        if (currentMembershipLevel === OrganizationMembershipLevel.Owner) {
            return null
        }
        if (newLevelOrAllowedLevels > currentMembershipLevel) {
            return 'You can only change access level of others to lower or equal to your current one.'
        }
    }
    if (currentMembershipLevel < OrganizationMembershipLevel.Admin) {
        return "You don't have permission to change access levels."
    }
    if (currentMembershipLevel < effectiveLevelToBeUpdated) {
        return 'You can only change access level of members with level lower or equal to you.'
    }
    return null
}

/** Check if a user has membership level in the given organization gte then the provided */
export function hasMembershipLevelOrHigher(org: OrganizationBasicType, role: OrganizationMembershipLevel): boolean {
    return !!(org.membership_level && org.membership_level >= role)
}

/** Check if an organization allows personal API keys */
export function organizationAllowsPersonalApiKeysForMembers(org: OrganizationBasicType): boolean {
    return !!org.members_can_use_personal_api_keys
}

export const membershipLevelToName = new Map<EitherMembershipLevel, string>([
    [OrganizationMembershipLevel.Member, 'member'],
    [OrganizationMembershipLevel.Admin, 'admin'],
    [OrganizationMembershipLevel.Owner, 'owner'],
])

export const organizationMembershipLevelIntegers = Object.values(OrganizationMembershipLevel).filter(
    (value) => typeof value === 'number'
) as OrganizationMembershipLevel[]

export const teamMembershipLevelIntegers = Object.values(TeamMembershipLevel).filter(
    (value) => typeof value === 'number'
) as TeamMembershipLevel[]
