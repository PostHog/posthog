import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationAI(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Enable Intelligence data analysis features"
                data-attr="organization-ai-enabled"
                onChange={(checked) => {
                    updateOrganization({ is_ai_data_processing_approved: checked })
                }}
                checked={!!currentOrganization?.is_ai_data_processing_approved}
                disabled={!!restrictionReason || currentOrganizationLoading}
                bordered
            />
        </div>
    )
}
