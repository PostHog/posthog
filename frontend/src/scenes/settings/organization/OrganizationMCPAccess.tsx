import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'

import { AvailableFeature } from '~/types'

export function OrganizationMCPAccess(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const adminRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <PayGateMini feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}>
            <LemonSwitch
                label={
                    <span>
                        Restrict MCP access to read-only{' '}
                        <Tooltip title="When enabled, anyone connecting to this organization through the PostHog MCP can read data but can't change it. This applies to every member, including admins. Each member's permissions still apply separately via access control. Using PostHog in the app or calling the API directly is not affected.">
                            <IconInfo className="mr-1" />
                        </Tooltip>
                    </span>
                }
                bordered
                data-attr="org-mcp-access-read-only-toggle"
                checked={!!currentOrganization?.read_only_mcp_access}
                onChange={(read_only_mcp_access) => {
                    updateOrganization({ read_only_mcp_access })
                }}
                disabled={currentOrganizationLoading}
                disabledReason={adminRestrictionReason}
            />
        </PayGateMini>
    )
}
