import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationMembershipLevelIntegers } from 'lib/utils/permissioning'

export interface InviteLevelOption {
    value: OrganizationMembershipLevel
    label: string
}

/** The levels an inviter may offer: their own level or lower, plus Guest for admins whose plan has guest access. */
export function inviteLevelOptions(
    myMembershipLevel: OrganizationMembershipLevel | null | undefined,
    canInviteGuests: boolean
): InviteLevelOption[] {
    const levels =
        myMembershipLevel != null
            ? organizationMembershipLevelIntegers.filter((level) => level <= myMembershipLevel)
            : [OrganizationMembershipLevel.Member]
    const withGuest =
        canInviteGuests && myMembershipLevel != null && myMembershipLevel >= OrganizationMembershipLevel.Admin
            ? [...levels, OrganizationMembershipLevel.Guest]
            : levels
    return withGuest.map((level) => ({ value: level, label: OrganizationMembershipLevel[level] }))
}
