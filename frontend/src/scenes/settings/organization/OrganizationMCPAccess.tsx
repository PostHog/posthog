import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { OrganizationSecuritySettingGate } from './OrganizationSecuritySettingGate'

const MCP_READ_ONLY_HELP =
    "When enabled, anyone connecting to this organization through the PostHog MCP can read data but can't change it. This applies to every member, including admins. Each member's permissions still apply separately via access control. Using PostHog in the app or calling the API directly is not affected."

export function OrganizationMCPAccess(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const adminRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (read_only_mcp_access: boolean): void => {
        updateOrganization({ read_only_mcp_access })
    }

    if (todayRailNav) {
        return (
            <OrganizationSecuritySettingGate featureDetail="organization-mcp-access">
                <QuillSettingSwitch
                    label="Restrict MCP access to read-only"
                    help={MCP_READ_ONLY_HELP}
                    dataAttr="org-mcp-access-read-only-toggle"
                    checked={!!currentOrganization?.read_only_mcp_access}
                    onCheckedChange={handleChange}
                    disabled={currentOrganizationLoading}
                    disabledReason={adminRestrictionReason}
                />
            </OrganizationSecuritySettingGate>
        )
    }

    return (
        <OrganizationSecuritySettingGate featureDetail="organization-mcp-access">
            <LemonSwitch
                label={
                    <span>
                        Restrict MCP access to read-only{' '}
                        <Tooltip title={MCP_READ_ONLY_HELP}>
                            <IconInfo className="mr-1" />
                        </Tooltip>
                    </span>
                }
                bordered
                data-attr="org-mcp-access-read-only-toggle"
                checked={!!currentOrganization?.read_only_mcp_access}
                onChange={handleChange}
                disabled={currentOrganizationLoading}
                disabledReason={adminRestrictionReason}
            />
        </OrganizationSecuritySettingGate>
    )
}
