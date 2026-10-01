import { useActions, useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { organizationLogic } from 'scenes/organizationLogic'

import { AvailableFeature } from '~/types'

export function Enforce2FA(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <PayGateMini
            feature={AvailableFeature.TWOFA_ENFORCEMENT}
            featureDetail="organization-members-two-factor-authentication"
        >
            <LemonSwitch
                label="Enforce 2FA"
                bordered
                checked={!!currentOrganization?.enforce_2fa}
                onChange={(enforce_2fa) => updateOrganization({ enforce_2fa })}
                loading={currentOrganizationLoading}
                disabledReason={restrictionReason}
            />
        </PayGateMini>
    )
}
