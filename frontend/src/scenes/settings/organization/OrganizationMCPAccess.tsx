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
                        <Tooltip title="When enabled, AI tools connected through PostHog's MCP server can read data in this organization but can't change it. This applies to every member, including admins. Access through the app and the API is not affected.">
                            <IconInfo className="mr-1" />
                        </Tooltip>
                    </span>
                }
                bordered
                data-attr="org-mcp-access-read-only-toggle"
                checked={!!currentOrganization?.mcp_access_read_only}
                onChange={(mcp_access_read_only) => {
                    updateOrganization({ mcp_access_read_only })
                }}
                disabled={currentOrganizationLoading}
                disabledReason={adminRestrictionReason}
            />
        </PayGateMini>
    )
}
