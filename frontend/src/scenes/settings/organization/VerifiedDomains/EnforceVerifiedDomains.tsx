import { useActions, useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { organizationLogic } from 'scenes/organizationLogic'

import { AvailableFeature } from '~/types'

import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function EnforceVerifiedDomains(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { verifiedDomains, verifiedDomainsLoading } = useValues(verifiedDomainsLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const hasVerifiedDomains = verifiedDomains.some((domain) => domain.is_verified)

    return (
        <PayGateMini feature={AvailableFeature.AUTOMATIC_PROVISIONING}>
            <p>
                Only allow people with an email address on a verified domain to log in or join this organization.
                Invites to other domains are blocked.
            </p>
            <LemonSwitch
                label="Require a verified email domain to log in"
                bordered
                checked={!!currentOrganization?.enforce_verified_domains}
                onChange={(enforce_verified_domains) => updateOrganization({ enforce_verified_domains })}
                loading={currentOrganizationLoading}
                disabledReason={
                    restrictionReason ??
                    (!verifiedDomainsLoading && !hasVerifiedDomains
                        ? 'Verify at least one domain to enable this setting'
                        : undefined)
                }
            />
        </PayGateMini>
    )
}
