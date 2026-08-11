import { useActions, useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function EnforceVerifiedDomains(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { verifiedDomains, verifiedDomainsLoading } = useValues(verifiedDomainsLogic)
    const { user } = useValues(userLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const hasVerifiedDomains = verifiedDomains.some((domain) => domain.is_verified)
    const ownEmailDomain = user?.email.split('@')[1]?.toLowerCase()
    const ownEmailDomainVerified = verifiedDomains.some(
        (domain) => domain.is_verified && domain.domain.toLowerCase() === ownEmailDomain
    )

    // Only gates turning it on — an organization that ends up misconfigured must still be able to turn it off.
    let enableBlockedReason: string | undefined
    if (!verifiedDomainsLoading && !currentOrganization?.enforce_verified_domains) {
        if (!hasVerifiedDomains) {
            enableBlockedReason = 'Verify at least one domain to enable this setting'
        } else if (!ownEmailDomainVerified) {
            enableBlockedReason = 'Verify the domain of your own email address first, otherwise this would lock you out'
        }
    }

    return (
        <PayGateMini feature={AvailableFeature.AUTOMATIC_PROVISIONING}>
            <p>
                Only allow people with an email address on a verified domain into this organization. Invites to other
                domains are blocked, and existing members on other domains lose access.
            </p>
            <LemonSwitch
                label="Restrict membership to verified email domains"
                bordered
                checked={!!currentOrganization?.enforce_verified_domains}
                onChange={(enforce_verified_domains) => updateOrganization({ enforce_verified_domains })}
                loading={currentOrganizationLoading}
                disabledReason={restrictionReason ?? enableBlockedReason}
            />
        </PayGateMini>
    )
}
