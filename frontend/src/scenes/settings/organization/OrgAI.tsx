import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { AI_DATA_PROCESSING_LOCKED_REASON } from '~/layout/ai/aiConsentLogic'

import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function OrganizationAI(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const checked = !!currentOrganization?.is_ai_data_processing_approved
    // The lock only stops turning AI on, so an organization that is locked can still turn it off.
    const disabledReason =
        currentOrganization?.is_ai_data_processing_locked && !checked
            ? AI_DATA_PROCESSING_LOCKED_REASON
            : restrictionReason
              ? ORG_ADMIN_REQUIRED_TOOLTIP
              : undefined

    const handleChange = (value: boolean): void => {
        updateOrganization({ is_ai_data_processing_approved: value })
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Enable PostHog features that use third-party AI services"
                dataAttr="organization-ai-enabled"
                checked={checked}
                onCheckedChange={handleChange}
                disabled={currentOrganizationLoading}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <div className="max-w-160">
            <LemonSwitch
                label="Enable PostHog features that use third-party AI services"
                data-attr="organization-ai-enabled"
                onChange={handleChange}
                checked={checked}
                disabledReason={disabledReason}
                loading={currentOrganizationLoading}
                bordered
            />
        </div>
    )
}
