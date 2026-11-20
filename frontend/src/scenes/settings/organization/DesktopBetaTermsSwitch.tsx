import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { desktopBetaTermsLogic } from './desktopBetaTermsLogic'
import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function DesktopBetaTermsSwitch({ projectId }: { projectId: string }): JSX.Element {
    const logic = desktopBetaTermsLogic({ projectId })
    const { desktopBetaTermsAccepted, desktopBetaTermsAcceptedLoading } = useValues(logic)
    const { acceptDesktopBetaTerms } = useActions(logic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const disabledReason = restrictionReason
        ? ORG_ADMIN_REQUIRED_TOOLTIP
        : desktopBetaTermsAccepted
          ? 'The PostHog Desktop beta terms have already been accepted for this organization.'
          : undefined

    const handleChange = (checked: boolean): void => {
        if (checked) {
            acceptDesktopBetaTerms()
        }
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Accept beta terms"
                dataAttr="organization-desktop-beta-terms-accepted"
                checked={desktopBetaTermsAccepted === true}
                onCheckedChange={handleChange}
                disabled={desktopBetaTermsAcceptedLoading}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Accept beta terms"
                data-attr="organization-desktop-beta-terms-accepted"
                onChange={handleChange}
                checked={desktopBetaTermsAccepted === true}
                disabledReason={disabledReason}
                loading={desktopBetaTermsAcceptedLoading}
                bordered
            />
        </div>
    )
}
