import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { teamLogic } from 'scenes/teamLogic'

export function RequireFeatureFlagTags(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const handleToggle = (enabled: boolean): void => {
        updateCurrentTeam({ feature_flag_policy_config: { require_tags: enabled } })
    }

    return (
        <LemonSwitch
            data-attr="require-feature-flag-tags-switch"
            onChange={handleToggle}
            label="Require tags on new flags"
            bordered
            checked={currentTeam?.feature_flag_policy_config?.require_tags || false}
            disabled={currentTeamLoading}
            disabledReason={restrictedReason}
        />
    )
}
