import posthog from 'posthog-js'

import { retryWithBackoff } from 'lib/utils/async'
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

const teamFieldsListeners = new Set<() => void>()

/** For a logic that reads the full stage team fields from the app context once, on mount. Returns the unsubscribe. */
export function onFullStageTeamFieldsApplied(listener: () => void): () => void {
    teamFieldsListeners.add(listener)
    return () => teamFieldsListeners.delete(listener)
}

export function applyFullStageAppContext(fullStage: FullStageAppContext): void {
    const context = getAppContext()
    if (!context) {
        return
    }
    // Merge in place too, so a logic that mounts after this reads the fields from the app context.
    if (context.current_user) {
        Object.assign(context.current_user, fullStage.current_user)
    }
    userLogic.findMounted()?.actions.addFullStageUserFields(fullStage.current_user)

    // The server sends the user's current team, which can differ from the page's team after a switch in another tab.
    const fullStageTeam = fullStage.current_team
    const teamId = fullStageTeam?.id
    if (fullStageTeam && teamId !== undefined && context.current_team?.id === teamId) {
        Object.assign(context.current_team, fullStageTeam)
        if (context.current_project) {
            Object.assign(context.current_project, fullStage.current_project)
        }
        context.has_person_email = fullStage.has_person_email ?? false
        const mountedTeamLogic = teamLogic.findMounted()
        if (mountedTeamLogic?.values.currentTeam?.id === teamId) {
            mountedTeamLogic.actions.addFullStageTeamFields(fullStageTeam)
        }
        teamFieldsListeners.forEach((listener) => listener())
    }
}

/**
 * A deferred page boots without the fields the first screen does not read. This fetches them after the boot.
 */
export function loadFullStageAppContext(): void {
    if (!window.POSTHOG_APP_CONTEXT_REQUEST) {
        return
    }
    const teamId = getAppContext()?.current_team?.id
    const projectPrefix = teamId ? `/project/${teamId}` : ''
    void retryWithBackoff(async () => {
        const response = await fetch(`${projectPrefix}/_app_context?stage=full`, { credentials: 'same-origin' })
        if (!response.ok) {
            throw new Error(`The full stage app context request failed with status ${response.status}`)
        }
        return (await response.json()) as { app_context: FullStageAppContext }
    })
        .then((body) => applyFullStageAppContext(body.app_context))
        .catch((error) => posthog.captureException(error))
}
