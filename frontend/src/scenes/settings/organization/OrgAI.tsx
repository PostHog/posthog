import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function OrganizationAI(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateOrganization({ is_ai_data_processing_approved: checked })
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Enable PostHog features that use third-party AI services"
                dataAttr="organization-ai-enabled"
                checked={!!currentOrganization?.is_ai_data_processing_approved}
                onCheckedChange={handleChange}
                disabled={currentOrganizationLoading}
                disabledReason={restrictionReason ? ORG_ADMIN_REQUIRED_TOOLTIP : undefined}
            />
        )
    }

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Enable PostHog features that use third-party AI services"
                data-attr="organization-ai-enabled"
                onChange={handleChange}
                checked={!!currentOrganization?.is_ai_data_processing_approved}
                disabledReason={restrictionReason ? ORG_ADMIN_REQUIRED_TOOLTIP : undefined}
                loading={currentOrganizationLoading}
                bordered
            />
        </div>
    )
}
