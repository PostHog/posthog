import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { projectLogic } from 'scenes/projectLogic'

import { desktopBetaTermsLogic } from './desktopBetaTermsLogic'
import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function OrganizationDesktopBetaTerms(): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const logic = desktopBetaTermsLogic({ projectId: String(currentProjectId ?? '@current') })
    const { desktopBetaTermsAccepted, desktopBetaTermsAcceptedLoading } = useValues(logic)
    const { acceptDesktopBetaTerms, revokeDesktopBetaTerms } = useActions(logic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Accept beta terms"
                data-attr="organization-desktop-beta-terms-accepted"
                onChange={(checked) => {
                    if (checked) {
                        acceptDesktopBetaTerms()
                    } else {
                        revokeDesktopBetaTerms()
                    }
                }}
                checked={desktopBetaTermsAccepted === true}
                disabledReason={restrictionReason ? ORG_ADMIN_REQUIRED_TOOLTIP : undefined}
                loading={desktopBetaTermsAcceptedLoading}
                bordered
            />
            <p className="mt-2 text-muted text-sm">
                PostHog Desktop will ask for these terms to be accepted again after acceptance is withdrawn. Withdrawing
                acceptance does not undo data processing that has already occurred.
            </p>
        </div>
    )
}
