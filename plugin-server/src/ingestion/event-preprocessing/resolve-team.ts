import { Message } from 'node-rdkafka'

import { TeamManager } from '~/utils/team-manager'

import { eventDroppedCounter } from '../../common/metrics'
import { EventHeaders, IncomingEvent, IncomingEventWithTeam, Team } from '../../types'
import { tokenOrTeamPresentCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface ResolveTeamStepInput {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
}

export interface ResolveTeamStepOutput {
    eventWithTeam: IncomingEventWithTeam
    team: Team
}

type ResolveTeamError = { error: true; cause: 'no_token' | 'invalid_token' }
type ResolveTeamSuccess = { error: false } & ResolveTeamStepOutput
type ResolveTeamResult = ResolveTeamSuccess | ResolveTeamError

async function resolveTeam(
    teamManager: TeamManager,
    message: Message,
    headers: EventHeaders,
    event: IncomingEvent['event']
): Promise<ResolveTeamResult> {
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: event.team_id ? 'true' : 'false',
            token_present: event.token ? 'true' : 'false',
        })
        .inc()

    // Events with no token are dropped, they should be blocked by capture
    if (!event.token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return { error: true, cause: 'no_token' }
    }

    const team = await teamManager.getTeamByToken(event.token)
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return { error: true, cause: 'invalid_token' }
    }

    return {
        error: false,
        team,
        eventWithTeam: {
            event,
            team,
            message,
            headers,
        },
    }
}

export function createResolveTeamStep<TInput extends ResolveTeamStepInput>(
    teamManager: TeamManager
): ProcessingStep<TInput, TInput & ResolveTeamStepOutput> {
    return async function resolveTeamStep(input) {
        const { message, headers, event } = input

        const result = await resolveTeam(teamManager, message, headers, event.event)

        if (result.error) {
            return drop(result.cause)
        }

        return ok({ ...input, eventWithTeam: result.eventWithTeam, team: result.team })
    }
}
