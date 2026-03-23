import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export function PersonLastSeenAtEnabled(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const checked = currentTeam?.extra_settings?.person_last_seen_at_enabled === true

    return (
        <LemonSwitch
            onChange={(newChecked) => {
                updateCurrentTeam({
                    extra_settings: {
                        ...currentTeam?.extra_settings,
                        person_last_seen_at_enabled: newChecked,
                    },
                })
            }}
            checked={checked}
            loading={currentTeamLoading}
            disabledReason={restrictedReason}
            label="Track when a person was last seen"
            bordered
        />
    )
}
