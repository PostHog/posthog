import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationAdvertisingRetargeting(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Allow retargeting"
                data-attr="organization-advertising-retargeting-enabled"
                onChange={(checked) => {
                    updateOrganization({ allow_advertising_retargeting: checked })
                }}
                checked={!!currentOrganization?.allow_advertising_retargeting}
                disabled={!!restrictionReason || currentOrganizationLoading}
                bordered
            />
        </div>
    )
}
