import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export function CrossProjectQuerySettings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <div className="deprecated-space-y-2">
            <p className="flex items-center gap-1 mb-0">
                Allow this project to query other projects in the same organization with HogQL.
                <Tooltip title="When enabled, HogQL queries from this project can run across other projects in the organization. Every query still validates the requested project scope when it executes.">
                    <IconInfo className="text-lg" />
                </Tooltip>
            </p>
            <LemonSwitch
                id="posthog-cross-project-query-switch"
                checked={!!currentTeam?.can_query_across_organization_projects}
                onChange={(checked) => updateCurrentTeam({ can_query_across_organization_projects: checked })}
                disabledReason={restrictedReason || undefined}
                label="Query across all projects in this organization"
                bordered
            />
        </div>
    )
}
