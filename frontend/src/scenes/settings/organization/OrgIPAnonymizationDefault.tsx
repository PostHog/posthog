import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { organizationLogic } from '~/scenes/organizationLogic'

import { ORG_ADMIN_REQUIRED_TOOLTIP } from './organizationSettingsConstants'

export function OrgIPAnonymizationDefault(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateOrganization({ default_anonymize_ips: checked })
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label="Discard client IP data by default for new projects"
                checked={!!currentOrganization?.default_anonymize_ips}
                onCheckedChange={handleChange}
                disabled={currentOrganizationLoading}
                disabledReason={restrictionReason ? ORG_ADMIN_REQUIRED_TOOLTIP : undefined}
            />
        )
    }

    return (
        <LemonSwitch
            onChange={handleChange}
            checked={!!currentOrganization?.default_anonymize_ips}
            disabledReason={restrictionReason ? ORG_ADMIN_REQUIRED_TOOLTIP : undefined}
            loading={currentOrganizationLoading}
            label="Discard client IP data by default for new projects"
            bordered
        />
    )
}
