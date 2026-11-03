import { getAppContext } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { ProjectType, TeamType, UserType } from '~/types'

// pinned: the fields `full_stage_user_app_context` in posthog/utils.py returns
export interface FullStageAppContext {
    current_user: Partial<UserType>
    current_team?: Partial<TeamType>
    current_project?: Partial<ProjectType>
    has_person_email?: boolean
}

export function applyFullStageAppContext(teamId: number, fullStage: FullStageAppContext): void {
    const context = getAppContext()
    if (!context) {
        return
    }
    // Merge in place too, so a logic that mounts after this reads the fields from the app context.
    if (context.current_user) {
        Object.assign(context.current_user, fullStage.current_user)
    }
    userLogic.findMounted()?.actions.addFullStageUserFields(fullStage.current_user)

    if (fullStage.current_team && context.current_team?.id === teamId) {
        Object.assign(context.current_team, fullStage.current_team)
        if (context.current_project) {
            Object.assign(context.current_project, fullStage.current_project)
        }
        context.has_person_email = fullStage.has_person_email ?? false
        const mountedTeamLogic = teamLogic.findMounted()
        const currentTeam = mountedTeamLogic?.values.currentTeam
        if (mountedTeamLogic && currentTeam?.id === teamId) {
            mountedTeamLogic.actions.loadCurrentTeamSuccess({ ...currentTeam, ...fullStage.current_team })
        }
    }
}

/**
 * A deferred page boots without the fields the first screen does not read. This fetches them after the boot.
 */
export function loadFullStageAppContext(): void {
    const teamId = getAppContext()?.current_team?.id
    if (!window.POSTHOG_APP_CONTEXT_REQUEST || !teamId) {
        return
    }
    void fetch(`/project/${teamId}/_app_context?stage=full`, { credentials: 'same-origin' })
        .then((response) => (response.ok ? (response.json() as Promise<{ app_context: FullStageAppContext }>) : null))
        .then((body) => body && applyFullStageAppContext(teamId, body.app_context))
        .catch(() => {})
}
