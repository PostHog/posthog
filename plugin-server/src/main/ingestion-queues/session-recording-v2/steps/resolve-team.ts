import { Message } from 'node-rdkafka'

import { PipelineResult, dlq, drop, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { EventHeaders } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { TeamService } from '../teams/team-service'
import { TeamForReplay } from '../teams/types'

type Input = { message: Message; headers: EventHeaders; parsedMessage: ParsedMessageData }
type Output = {
    message: Message
    headers: EventHeaders
    parsedMessage: ParsedMessageData
    team: TeamForReplay
}

export function createResolveTeamStep(teamService: TeamService): ProcessingStep<Input, Output> {
    return async function resolveTeamStep(input: Input): Promise<PipelineResult<Output>> {
        const { message, headers, parsedMessage } = input

        if (!headers.token) {
            return dlq('no_token_in_header')
        }

        const team = await teamService.getTeamByToken(headers.token)
        if (!team) {
            return drop('header_token_present_team_missing_or_disabled')
        }

        const retentionPeriod = await teamService.getRetentionPeriodByTeamId(team.teamId)
        if (!retentionPeriod) {
            return drop('team_missing_retention_period')
        }

        return ok({
            message,
            headers,
            parsedMessage,
            team,
        })
    }
}
