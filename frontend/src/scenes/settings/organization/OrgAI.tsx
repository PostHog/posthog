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
                label="Enable PostHog features that use third-party AI services"
                data-attr="organization-ai-enabled"
                onChange={(checked) => {
                    updateOrganization({ is_ai_data_processing_approved: checked })
                }}
                checked={!!currentOrganization?.is_ai_data_processing_approved}
                disabledReason={
                    restrictionReason
                        ? 'You must be an admin or owner of your organization to change this setting'
                        : undefined
                }
                loading={currentOrganizationLoading}
                bordered
            />
        </div>
    )
}
