import { fullName } from 'lib/utils/strings'

import { OrganizationMemberType } from '~/types'

/** A member's name, or their email when they never set one. Invited and SSO users often have no name. */
export function memberDisplayName(member: OrganizationMemberType): string {
    return fullName(member.user) || member.user.email
}
