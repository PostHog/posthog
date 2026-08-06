import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '~/common/metrics'
import { TeamManager } from '~/common/utils/team-manager'
import { tokenOrTeamPresentCounter } from '~/ingestion/common/metrics'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, IncomingEvent, Team } from '~/types'

export interface ResolveTeamStepInput {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
}

type ResolveTeamError = { error: true; cause: 'no_token' | 'invalid_token' }
type ResolveTeamSuccess = { error: false; team: Team }
type ResolveTeamResult = ResolveTeamSuccess | ResolveTeamError

async function resolveTeam(
    teamManager: TeamManager,
    token: string | undefined,
    teamId: number | null | undefined
): Promise<ResolveTeamResult> {
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: teamId ? 'true' : 'false',
            token_present: token ? 'true' : 'false',
        })
        .inc()

    // Events with no token are dropped, they should be blocked by capture
    if (!token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return { error: true, cause: 'no_token' }
    }

    const team = await teamManager.getTeamByToken(token)
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return { error: true, cause: 'invalid_token' }
    }

    return { error: false, team }
}

export function createResolveTeamStep<TInput extends ResolveTeamStepInput>(
    teamManager: TeamManager
): ProcessingStep<TInput, Omit<TInput, 'event'> & { event: PluginEvent; team: Team }> {
    return async function resolveTeamStep(input) {
        const { event: incomingEvent, ...restInput } = input

        const result = await resolveTeam(teamManager, input.headers.token, incomingEvent.event.team_id)

        if (result.error) {
            return drop(result.cause)
        }

        const pluginEvent: PluginEvent = { ...incomingEvent.event, team_id: result.team.id }
        return ok({ ...restInput, event: pluginEvent, team: result.team })
    }
}
