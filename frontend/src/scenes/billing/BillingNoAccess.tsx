import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { OrganizationMembershipLevel } from 'lib/constants'
import { fullName } from 'lib/utils/strings'
import { billingLogic } from 'scenes/billing/billingLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { urls } from 'scenes/urls'

interface BillingNoAccessProps {
    title?: string
    reason: string
}

export function BillingNoAccess({ title = 'Billing', reason }: BillingNoAccessProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { minimumBillingAccessLevel } = useValues(billingLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useEffect(() => {
        ensureAllMembersLoaded()
    }, [ensureAllMembersLoaded])

    // Only offer people who can actually change billing. With owner-only billing enabled the minimum
    // level is Owner, so admins (who are blocked too, and may be the reader) are left off the list.
    const billingContacts = meFirstMembers
        .filter((member) => member.level >= minimumBillingAccessLevel)
        .sort((a, b) => b.level - a.level)
        .slice(0, 5)

    const contactRole = minimumBillingAccessLevel === OrganizationMembershipLevel.Owner ? 'owner' : 'admin'

    return (
        <div className="deprecated-space-y-4">
            <h1>{title}</h1>
            <LemonBanner type="warning">{reason}</LemonBanner>
            {billingContacts.length > 0 && (
                <div>
                    <p className="mb-2">Ask an organization {contactRole} to make billing changes:</p>
                    <ul className="deprecated-space-y-1">
                        {billingContacts.map((member) => (
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
