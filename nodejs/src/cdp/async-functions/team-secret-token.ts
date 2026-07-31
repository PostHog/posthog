import { captureException } from '~/common/utils/posthog'
import { Team } from '~/types'

import { AsyncFunctionContext } from '../async-function-registry'

/**
 * Support and customer analytics ticket/account actions authenticate with the team's legacy
 * secret API token. Nothing provisions it automatically for most projects, so this is the
 * dead end users hit when it's missing — point them at where to fix it instead of naming
 * an internal team ID, and capture it so the failure is visible in error tracking.
 */
export async function getTeamWithSecretToken(context: AsyncFunctionContext, functionName: string): Promise<Team> {
    const team = await context.teamManager.getTeam(context.invocation.teamId)
    if (!team) {
        throw new Error(`Team ${context.invocation.teamId} not found`)
    }
    if (!team.secret_api_token) {
        const error = new Error(
            'Support is not fully set up for this project: no secret API key is configured. ' +
                'Go to Support settings > General and generate a secret API key, then re-run this action.'
        )
        captureException(error, {
            tags: {
                team_id: context.invocation.teamId,
                function: functionName,
                template_id: context.invocation.hogFunction.template_id ?? null,
            },
        })
        throw error
    }
    return team
}
