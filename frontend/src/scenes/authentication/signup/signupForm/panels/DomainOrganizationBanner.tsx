import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { DomainOrganization, signupLogic } from '../signupLogic'

export function DomainOrganizationBanner({
    organization,
    email,
}: {
    organization: DomainOrganization
    email: string
}): JSX.Element {
    const { organizationAccessRequestStatus } = useValues(signupLogic)
    const { requestOrganizationAccess, dismissDomainOrganization } = useActions(signupLogic)
    const organizationName = organization.organization_name

    return (
        <div className="deprecated-space-y-4 Signup__panel__domain-organization">
            <h2 className="m-0">
                {organizationName
                    ? 'Your team is already on PostHog'
                    : `Someone at ${organization.domain} already uses PostHog`}
            </h2>
            <p className="text-secondary mb-0">
                {organizationName ? (
                    <>
                        <b>{organizationName}</b> uses PostHog with {organization.domain} email addresses.
                    </>
                ) : (
                    <>An organization on your email domain is already using PostHog.</>
                )}{' '}
                Ask an admin for an invite so your work lands next to your team's, instead of in a separate
                organization.
            </p>
            {organizationAccessRequestStatus === 'sent' ? (
                <LemonBanner type="success">
                    Sent. An admin will get an email asking them to invite you. Once they do, your invite link arrives
                    at {email}.
                </LemonBanner>
            ) : (
                <>
                    {organizationAccessRequestStatus === 'failed' && (
                        <LemonBanner type="warning">
                            We couldn't reach an admin. Ask a teammate to invite you from the organization's members
                            settings, or create your own organization below.
                        </LemonBanner>
                    )}
                    <LemonButton
                        type="primary"
                        status="alt"
                        fullWidth
                        center
                        size="large"
                        onClick={() => requestOrganizationAccess(email)}
                        loading={organizationAccessRequestStatus === 'pending'}
                        data-attr="domain-organization-request-access"
                    >
                        Ask an admin to invite me
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        onClick={dismissDomainOrganization}
                        data-attr="domain-organization-create-own-org"
                    >
                        I'd like to create my own organization
                    </LemonButton>
                </>
            )}
        </div>
    )
}
