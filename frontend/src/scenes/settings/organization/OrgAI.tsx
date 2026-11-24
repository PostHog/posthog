import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { AI_DATA_PROCESSING_LOCKED_REASON } from '~/layout/ai/aiConsentLogic'

import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

const NO_DATA_ACCESS_LABEL = "Don't let PostHog AI see project data"
const NO_DATA_ACCESS_HELP =
    "PostHog AI can still create and change insights, dashboards, feature flags and more. It can't read events, persons, recordings or query results, and charts load only in the user's browser. Text that a person types in the chat is still sent."

export function OrganizationAI(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const posthogAiV2 = useFeatureFlag('PHAI_SANDBOX_MODE')

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

    const noDataAccess = currentOrganization?.ai_data_access === 'metadata_only'
    const noDataAccessDisabledReason = restrictionReason
        ? ORG_ADMIN_REQUIRED_TOOLTIP
        : !checked
          ? 'Turn on AI features first.'
          : undefined
    const handleNoDataAccessChange = (value: boolean): void => {
        updateOrganization({ ai_data_access: value ? 'metadata_only' : 'full' })
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <QuillSettingSwitch
                    label="Enable PostHog features that use third-party AI services"
                    dataAttr="organization-ai-enabled"
                    checked={checked}
                    onCheckedChange={handleChange}
                    disabled={currentOrganizationLoading}
                    disabledReason={disabledReason}
                />
                {posthogAiV2 && (
                    <QuillSettingSwitch
                        label={NO_DATA_ACCESS_LABEL}
                        help={NO_DATA_ACCESS_HELP}
                        dataAttr="organization-ai-no-data-access"
                        checked={noDataAccess}
                        onCheckedChange={handleNoDataAccessChange}
                        disabled={currentOrganizationLoading}
                        disabledReason={noDataAccessDisabledReason}
                    />
                )}
            </div>
        )
    }

    return (
        <div className="max-w-160 flex flex-col gap-2">
            <LemonSwitch
                label="Enable PostHog features that use third-party AI services"
                data-attr="organization-ai-enabled"
                onChange={handleChange}
                checked={checked}
                disabledReason={disabledReason}
                loading={currentOrganizationLoading}
                bordered
            />
            {posthogAiV2 && (
                <LemonSwitch
                    label={
                        <span>
                            {NO_DATA_ACCESS_LABEL}{' '}
                            <Tooltip title={NO_DATA_ACCESS_HELP}>
                                <IconInfo className="mr-1" />
                            </Tooltip>
                        </span>
                    }
                    data-attr="organization-ai-no-data-access"
                    onChange={handleNoDataAccessChange}
                    checked={noDataAccess}
                    disabledReason={noDataAccessDisabledReason}
                    loading={currentOrganizationLoading}
                    bordered
                />
            )}
        </div>
    )
}
