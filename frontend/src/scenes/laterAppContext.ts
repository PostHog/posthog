import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { ProjectType, TeamType, UserType } from '~/types'

// pinned: the fields `later_user_app_context` in posthog/utils.py returns
export interface LaterAppContext {
    current_user: Partial<UserType>
    current_team?: Partial<TeamType>
    current_project?: Partial<ProjectType>
    has_person_email?: boolean
}

export function applyLaterAppContext(teamId: number, later: LaterAppContext): void {
    const context = getAppContext()
    if (!context) {
        return
    }
    // Merge in place too, so a logic that mounts after this reads the fields from the app context.
    if (context.current_user) {
        Object.assign(context.current_user, later.current_user)
    }
    userLogic.findMounted()?.actions.addLaterUserFields(later.current_user)

    if (later.current_team && context.current_team?.id === teamId) {
        Object.assign(context.current_team, later.current_team)
        if (context.current_project) {
            Object.assign(context.current_project, later.current_project)
        }
        context.has_person_email = later.has_person_email ?? false
        const mountedTeamLogic = teamLogic.findMounted()
        const currentTeam = mountedTeamLogic?.values.currentTeam
        if (mountedTeamLogic && currentTeam?.id === teamId) {
            mountedTeamLogic.actions.loadCurrentTeamSuccess({ ...currentTeam, ...later.current_team })
        }
    }
}

/**
 * A deferred page boots without the fields the first screen does not read. This fetches them after the boot.
 */
export function loadLaterAppContext(): void {
    const teamId = getAppContext()?.current_team?.id
    if (!window.POSTHOG_APP_CONTEXT_REQUEST || !teamId) {
        return
    }
    void fetch(`/project/${teamId}/_app_context/later`, { credentials: 'same-origin' })
        .then((response) => (response.ok ? (response.json() as Promise<LaterAppContext>) : null))
        .then((later) => later && applyLaterAppContext(teamId, later))
        .catch(() => {})
}
