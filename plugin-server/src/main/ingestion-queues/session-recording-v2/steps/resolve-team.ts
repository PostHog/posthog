import { PipelineResult, dlq, drop, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { EventHeaders } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { TeamService } from '../teams/team-service'
import { TeamForReplay } from '../teams/types'

type Input = { headers: EventHeaders; parsedMessage: ParsedMessageData }
type Output = { team: TeamForReplay }

export function createResolveTeamStep<T extends Input>(teamService: TeamService): ProcessingStep<T, T & Output> {
    return async function resolveTeamStep(input: T): Promise<PipelineResult<T & Output>> {
        const { headers } = input

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
            ...input,
            team,
        })
    }
}
