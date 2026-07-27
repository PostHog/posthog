import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

// Only surface the read-only notice to members who actually lack access. Admins and owners can
// already change these settings, so telling them they can't is confusing noise.
export function OrganizationAdminNotice(): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)

    const membershipLevel = currentOrganization?.membership_level
    if (membershipLevel == null || membershipLevel >= OrganizationMembershipLevel.Admin) {
        return null
    }

    return (
        <LemonBanner type="info" className="my-4">
            You need to be an organization admin or owner to change these settings.
        </LemonBanner>
    )
}
