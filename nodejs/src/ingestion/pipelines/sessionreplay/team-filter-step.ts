import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { EventHeaders } from '~/types'

export type TeamTokenResolver = Pick<TeamService, 'getTeamByToken' | 'getRetentionPeriodByTeamId'>

export interface TeamFilterStepInput {
    headers: EventHeaders
}

export interface TeamFilterStepOutput {
    team: TeamForReplay
}

/**
 * Creates a step that validates team ownership and enriches messages with team context.
 * This step is additive - it preserves all input properties and adds team context.
 *
 * Error handling:
 * - DLQ: Missing token (capture should always add this, indicates a bug)
 * - DROP: Team not found or disabled (intentional business logic)
 * - DROP: Missing retention period (team configuration issue)
 */
export function createTeamFilterStep<T extends TeamFilterStepInput>(
    teamService: TeamTokenResolver
): ProcessingStep<T, T & TeamFilterStepOutput> {
    return async function teamFilterStep(input) {
        const { headers } = input

        const token = headers.token
        if (!token) {
            // DLQ: Capture should always add a token header. Missing token indicates a bug.
            return dlq('no_token_in_header')
        }

        const team = await teamService.getTeamByToken(token)
        if (!team) {
            // DROP: Team doesn't exist or has session recording disabled
            return drop('header_token_present_team_missing_or_disabled')
        }

        const retentionPeriod = await teamService.getRetentionPeriodByTeamId(team.teamId)
        if (!retentionPeriod) {
            // DROP: Team configuration issue - no retention period set
            return drop('team_missing_retention_period')
        }

        return ok({ ...input, team })
    }
}
