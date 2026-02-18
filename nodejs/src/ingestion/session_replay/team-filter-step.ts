import { MessageHeader } from 'node-rdkafka'

import { TeamForReplay } from '../../session-recording/teams/types'
import { TeamService } from '../../session-replay/shared/teams/team-service'
import { dlq, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { ParseMessageStepOutput } from './parse-message-step'

export interface TeamFilterStepInput {
    parsedMessage: ParseMessageStepOutput['parsedMessage']
}

export interface TeamFilterStepOutput {
    team: TeamForReplay
    parsedMessage: ParseMessageStepOutput['parsedMessage']
}

function readTokenFromHeaders(headers: MessageHeader[] | undefined): string | undefined {
    const tokenHeader = headers?.find((header: MessageHeader) => header.token)?.token
    return typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()
}

/**
 * Creates a step that validates team ownership and enriches messages with team context.
 *
 * Error handling:
 * - DLQ: Missing token header (capture should always add this, indicates a bug)
 * - DROP: Team not found or disabled (intentional business logic)
 * - DROP: Missing retention period (team configuration issue)
 */
export function createTeamFilterStep(
    teamService: TeamService
): ProcessingStep<TeamFilterStepInput, TeamFilterStepOutput> {
    return async function teamFilterStep(input) {
        const { parsedMessage } = input

        const token = readTokenFromHeaders(parsedMessage.headers)
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

        return ok({ team, parsedMessage })
    }
}
