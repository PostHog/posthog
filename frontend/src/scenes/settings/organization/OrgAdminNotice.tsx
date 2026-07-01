import { LemonBanner } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

export function OrganizationAdminNotice(): JSX.Element | null {
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    if (!restrictionReason) {
        return null
    }

    return (
        <LemonBanner type="info" className="my-4">
            You must be an organization admin or owner to change these settings.
        </LemonBanner>
    )
}
