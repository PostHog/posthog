import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import {
    getReasonForAccessLevelChangeProhibition,
    membershipLevelToName,
    organizationMembershipLevelIntegers,
} from 'lib/utils/permissioning'
import { fullName } from 'lib/utils/strings'

import { OrganizationMemberType, OrganizationType, UserType } from '~/types'

export interface MemberActionOptions {
    allowDeletion: boolean
    allowedLevels: OrganizationMembershipLevel[]
    disallowedReason: string | null
}

export function memberActionOptions(
    user: UserType,
    currentOrganization: OrganizationType | null,
    member: OrganizationMemberType
): MemberActionOptions {
    const currentMembershipLevel = currentOrganization?.membership_level ?? -1

    const allowDeletion =
        // higher-ranked users cannot be removed, at the same time the currently logged-in user can leave any time
        ((currentMembershipLevel >= OrganizationMembershipLevel.Admin && member.level <= currentMembershipLevel) ||
            member.user.uuid === user.uuid) &&
        // unless that user is the organization's owner, in which case they can't leave
        member.level !== OrganizationMembershipLevel.Owner

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    const allowedLevels = organizationMembershipLevelIntegers.filter(
        (listLevel) => !getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, listLevel)
    )
    const disallowedReason = getReasonForAccessLevelChangeProhibition(myMembershipLevel, user, member, allowedLevels)

    return { allowDeletion, allowedLevels, disallowedReason }
}

export function memberLevelChangeLabel(member: OrganizationMemberType, listLevel: OrganizationMembershipLevel): string {
    if (listLevel === OrganizationMembershipLevel.Owner) {
        return 'Make owner'
    }

    return listLevel > member.level
        ? `Upgrade to ${membershipLevelToName.get(listLevel)}`
        : `Downgrade to ${membershipLevelToName.get(listLevel)}`
}

export function changeMemberLevelWithConfirmation(
    user: UserType,
    member: OrganizationMemberType,
    listLevel: OrganizationMembershipLevel,
    changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => void
): void {
    if (listLevel === OrganizationMembershipLevel.Owner) {
        LemonDialog.open({
            title: `Add additional owner to ${user.organization?.name}?`,
            description: `Please confirm that you would like to make ${fullName(
                member.user
            )} an owner of ${user.organization?.name}.`,
            primaryButton: {
                status: 'danger',
                children: `Make ${fullName(member.user)} an owner`,
                onClick: () => changeMemberAccessLevel(member, listLevel),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    } else {
        changeMemberAccessLevel(member, listLevel)
    }
}
