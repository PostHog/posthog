import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

// A limit stops at the organization it was set in, so a person in several organizations can cap
// one and still be invoiced by another. Each link switches organization and lands on its billing.
export function BillingLimitOtherOrganizationsNote(): JSX.Element | null {
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)

    const switchableOrganizations = otherOrganizations.filter((organization) => organization.is_active !== false)
    if (switchableOrganizations.length === 0) {
        return null
    }

    return (
        <div className="text-xs text-secondary mb-2" data-attr="billing-limit-other-organizations-note">
            Billing limits apply to one organization. Set limits separately in{' '}
            {switchableOrganizations.map((organization, index) => (
                <Fragment key={organization.id}>
                    {index > 0 ? ', ' : ''}
                    <Link onClick={() => updateCurrentOrganization(organization.id, urls.organizationBilling())}>
                        {organization.name}
                    </Link>
                </Fragment>
            ))}
            .
        </div>
    )
}
