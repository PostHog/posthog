import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

import { desktopBetaTermsLogic } from './desktopBetaTermsLogic'
import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function OrganizationDesktopBetaTerms(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const logic = desktopBetaTermsLogic({ organizationId: currentOrganization?.id ?? '@current' })
    const { desktopBetaTermsAccepted, desktopBetaTermsAcceptedLoading } = useValues(logic)
    const { acceptDesktopBetaTerms } = useActions(logic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    const disabledReason = restrictionReason
        ? ORG_ADMIN_REQUIRED_TOOLTIP
        : desktopBetaTermsAccepted
          ? 'The PostHog Desktop beta terms have already been accepted for this organization.'
          : undefined

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Accept beta terms"
                data-attr="organization-desktop-beta-terms-accepted"
                onChange={(checked) => {
                    if (checked) {
                        acceptDesktopBetaTerms()
                    }
                }}
                checked={desktopBetaTermsAccepted === true}
                disabledReason={disabledReason}
                loading={desktopBetaTermsAcceptedLoading}
                bordered
            />
        </div>
    )
}
