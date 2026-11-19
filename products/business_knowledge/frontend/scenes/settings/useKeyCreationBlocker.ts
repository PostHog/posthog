import { useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

/** Why this user cannot create a key here, or null when they can. */
export function useKeyCreationBlocker(): string | null {
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: TeamMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })
    const { currentTeam } = useValues(teamLogic)

    if (restrictionReason) {
        return 'Ask a project admin to create a key here. Only admins can create keys.'
    }
    // The keys endpoint refuses a child environment, because business knowledge belongs to the project.
    if (!!currentTeam && currentTeam.id !== currentTeam.project_id) {
        return "Switch to this project's main environment to create a key. Business knowledge keys belong to the project."
    }
    return null
}
