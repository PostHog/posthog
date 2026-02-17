import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { TeamManager } from '~/utils/team-manager'

import { eventDroppedCounter } from '../../common/metrics'
import { EventHeaders, IncomingEvent, PipelineEvent, Team } from '../../types'
import { tokenOrTeamPresentCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface ResolveTeamStepInput {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
}

type ResolveTeamError = { error: true; cause: 'no_token' | 'invalid_token' }
type ResolveTeamSuccess = { error: false; team: Team }
type ResolveTeamResult = ResolveTeamSuccess | ResolveTeamError

async function resolveTeam(teamManager: TeamManager, event: PipelineEvent): Promise<ResolveTeamResult> {
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

    return { error: false, team }
}

export function createResolveTeamStep<TInput extends ResolveTeamStepInput>(
    teamManager: TeamManager
): ProcessingStep<TInput, Omit<TInput, 'event'> & { event: PluginEvent; team: Team }> {
    return async function resolveTeamStep(input) {
        const { event: incomingEvent, ...restInput } = input

        const result = await resolveTeam(teamManager, incomingEvent.event)

        if (result.error) {
            return drop(result.cause)
        }

        const pluginEvent: PluginEvent = { ...incomingEvent.event, team_id: result.team.id }
        return ok({ ...restInput, event: pluginEvent, team: result.team })
    }
}
