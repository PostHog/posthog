import { useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { OrganizationPersonalAPIKeysTable } from './OrganizationPersonalAPIKeysTable'

export function OrganizationPersonalAPIKeys(): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    // PayGateMini falls through to its children when billing carries no metadata for the feature,
    // so the entitlement is checked here too. Otherwise the table below mounts and its first
    // request comes back as a payment prompt.
    const entitled = hasAvailableFeature(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)

    if (restrictionReason) {
        return <p className="text-muted">{restrictionReason}</p>
    }

    return (
        <PayGateMini
            feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}
            featureDetail="organization-personal-api-keys"
        >
            {entitled ? <OrganizationPersonalAPIKeysTable /> : null}
        </PayGateMini>
    )
}
