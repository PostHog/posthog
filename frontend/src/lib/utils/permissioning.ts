import { OrganizationBasicType, OrganizationMemberType, UserType } from '../../types'
import { EitherMembershipLevel, OrganizationMembershipLevel, TeamMembershipLevel } from '../constants'

/** If access level change is disallowed given the circumstances, returns a reason why so. Otherwise returns null. */
export function getReasonForAccessLevelChangeProhibition(
    currentMembershipLevel: OrganizationMembershipLevel | null,
    currentUser: UserType,
    memberToBeUpdated: OrganizationMemberType,
    newLevelOrAllowedLevels: EitherMembershipLevel | EitherMembershipLevel[]
): null | string {
    if (memberToBeUpdated.user.uuid === currentUser.uuid) {
        return "You can't change your own access level."
    }
    if (!currentMembershipLevel) {
        return 'Your membership level is unknown.'
    }
    const effectiveLevelToBeUpdated = memberToBeUpdated.level
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

/** Whether the "remove from organization" action is offered for a member, and why it is disabled if it is. */
export function getMemberRemovalOption(
    currentMembershipLevel: OrganizationMembershipLevel | null,
    currentUser: UserType,
    memberToBeRemoved: OrganizationMemberType,
    allMembers: OrganizationMemberType[] | null
): { shown: boolean; disabledReason?: string } {
    const isSelf = memberToBeRemoved.user.uuid === currentUser.uuid
    const level = currentMembershipLevel ?? -1
    // Higher-ranked members cannot be removed, but anyone can leave on their own.
    const shown = (level >= OrganizationMembershipLevel.Admin && memberToBeRemoved.level <= level) || isSelf
    if (!shown) {
        return { shown: false }
    }
    // An owner row only offers removal to another owner, so removing someone else always leaves an owner behind.
    // Leaving yourself is the case that needs a second owner, which the API refuses without.
    if (isSelf && memberToBeRemoved.level === OrganizationMembershipLevel.Owner) {
        const anotherOwnerExists = !!allMembers?.some(
            (other) => other.level === OrganizationMembershipLevel.Owner && other.user.uuid !== currentUser.uuid
        )
        if (!anotherOwnerExists) {
            return {
                shown: true,
                disabledReason: "You can't leave the organization as its only owner. Make someone else an owner first.",
            }
        }
    }
    return { shown: true }
}

export const membershipLevelToName = new Map<EitherMembershipLevel, string>([
    [OrganizationMembershipLevel.Member, 'member'],
    [OrganizationMembershipLevel.Admin, 'admin'],
    [OrganizationMembershipLevel.Owner, 'owner'],
])

export function hasMembershipLevelOrHigher(org: OrganizationBasicType, role: OrganizationMembershipLevel): boolean {
    return org.membership_level !== null && org.membership_level >= role
}

export function organizationAllowsPersonalApiKeysForMembers(org: OrganizationBasicType): boolean {
    // undefined means the value is missing from the API response, so we treat it as true as a fallback
    return [true, undefined].includes(org.members_can_use_personal_api_keys)
}

export const organizationMembershipLevelIntegers = Object.values(OrganizationMembershipLevel).filter(
    (value) => typeof value === 'number'
) as OrganizationMembershipLevel[]

export const teamMembershipLevelIntegers = Object.values(TeamMembershipLevel).filter(
    (value) => typeof value === 'number'
) as TeamMembershipLevel[]
