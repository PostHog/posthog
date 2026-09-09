import { captureException } from '~/common/utils/posthog'
import { Team } from '~/types'

import { AsyncFunctionContext } from '../async-function-registry'

/**
 * Loads the team for a workflow action that calls back into PostHog's own API (tickets,
 * accounts), which authenticates with the project's secret API token.
 *
 * Nothing provisions that token: enabling Support mints only the public widget token, so a
 * project can be using tickets for months and still not have one. The message therefore names
 * the setup step rather than the field - it reaches the customer verbatim in the workflow's
 * logs, wrapped as "Workflow encountered an error: <message> at <action>". Keep it free of
 * square brackets, which the log viewer parses as entity chips and would swallow.
 *
 * `actionDescription` completes "so ... can't authenticate", e.g. 'ticket workflow actions'.
 */
export async function getTeamWithSecretToken(
    context: AsyncFunctionContext,
    functionName: string,
    actionDescription: string
): Promise<Team> {
    const team = await context.teamManager.getTeam(context.invocation.teamId)
    if (!team) {
        throw new Error(`Team ${context.invocation.teamId} not found`)
    }
    if (!team.secret_api_token) {
        // Naming the admin requirement matters: rotate_secret_token is gated by
        // TeamMemberStrictManagementPermission, so a regular member following the
        // instructions would otherwise reach a disabled button.
        const error = new Error(
            `This project has no secret API key, so ${actionDescription} can't authenticate. ` +
                `A project admin can generate one in Settings > Support > Secret API key.`
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
