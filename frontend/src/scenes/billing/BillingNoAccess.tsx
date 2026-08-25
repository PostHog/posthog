import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'
import { urls } from 'scenes/urls'

interface BillingNoAccessProps {
    title?: string
    reason: string
}

export function BillingNoAccess({ title = 'Billing', reason }: BillingNoAccessProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useEffect(() => {
        ensureAllMembersLoaded()
    }, [ensureAllMembersLoaded])

    const admins = meFirstMembers
        .filter((member) => member.level >= OrganizationMembershipLevel.Admin)
        .sort((a, b) => b.level - a.level)
        .slice(0, 5)

    return (
        <div className="deprecated-space-y-4">
            <h1>{title}</h1>
            <LemonBanner type="warning">{reason}</LemonBanner>
            {admins.length > 0 && (
                <div>
                    <p className="mb-2">Ask an organization admin to make billing changes:</p>
                    <ul className="deprecated-space-y-1">
                        {admins.map((member) => (
                            <li key={member.user.uuid}>
                                <Link to={`mailto:${member.user.email}`}>{fullName(member.user)}</Link>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <div className="flex">
                <LemonButton type="primary" to={urls.default()}>
                    Go back home
                </LemonButton>
            </div>
        </div>
    )
}
