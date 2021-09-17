import { OrganizationMemberType, UserType } from '../../types'
import { OrganizationMembershipLevel } from '../constants'

export function getReasonForAccessLevelChangeProhibition(
    currentMembershipLevel: OrganizationMembershipLevel | null,
    currentUser: UserType,
    memberChanged: OrganizationMemberType,
    newLevelOrAllowedLevels: OrganizationMembershipLevel | OrganizationMembershipLevel[]
): false | string {
    if (memberChanged.user.uuid === currentUser.uuid) {
        return "You can't change your own access level."
    }
    if (!currentMembershipLevel) {
        return 'Your membership level is unknown.'
    }
    if (Array.isArray(newLevelOrAllowedLevels)) {
        if (currentMembershipLevel === OrganizationMembershipLevel.Owner) {
            return false
        }
        if (!newLevelOrAllowedLevels.length) {
            return "You don't have permission to change this member's access level."
        }
    } else {
        if (newLevelOrAllowedLevels === memberChanged.level) {
            return "It doesn't make sense to set the same level as before."
        }
        if (currentMembershipLevel === OrganizationMembershipLevel.Owner) {
            return false
        }
        if (newLevelOrAllowedLevels > currentMembershipLevel) {
            return 'You can only change access level of others to lower or equal to your current one.'
        }
    }
    if (currentMembershipLevel < OrganizationMembershipLevel.Admin) {
        return "You don't have permission to change access levels."
    }
    if (currentMembershipLevel < memberChanged.level) {
        return 'You can only change access level of members with level lower or equal to you.'
    }
    return false
}
