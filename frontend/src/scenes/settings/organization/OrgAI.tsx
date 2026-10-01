import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function OrganizationAI(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const hasSignedBaa = !!currentOrganization?.has_signed_baa
    const isApproved = !!currentOrganization?.is_ai_data_processing_approved

    // Turning it off stays possible, so an organization that signed a BAA with AI on can still opt out.
    const disabledReason =
        hasSignedBaa && !isApproved
            ? 'Organizations with a signed BAA keep PostHog AI turned off. Contact us if this needs to change.'
            : restrictionReason
              ? ORG_ADMIN_REQUIRED_TOOLTIP
              : undefined

    return (
        <div className="max-w-160">
            {hasSignedBaa && (
                <p className="mb-2 text-sm text-secondary">
                    You have a signed BAA with PostHog. The BAA does not cover the third-party AI services these
                    features use, so you cannot turn them on.
                </p>
            )}
            <LemonSwitch
                label="Enable PostHog features that use third-party AI services"
                data-attr="organization-ai-enabled"
                onChange={(checked) => {
                    updateOrganization({ is_ai_data_processing_approved: checked })
                }}
                checked={isApproved}
                disabledReason={disabledReason}
                loading={currentOrganizationLoading}
                bordered
            />
        </div>
    )
}
