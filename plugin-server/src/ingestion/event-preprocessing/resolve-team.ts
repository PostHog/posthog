import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventHeaders, Hub, IncomingEvent, IncomingEventWithTeam } from '../../types'
import { tokenOrTeamPresentCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

async function resolveTeam(
    hub: Pick<Hub, 'teamManager'>,
    message: Message,
    headers: EventHeaders,
    event: IncomingEvent['event']
): Promise<IncomingEventWithTeam | null> {
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
        return null
    }

    const team = await hub.teamManager.getTeamByToken(event.token)
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return null
    }

    return {
        event,
        team,
        message,
        headers,
    }
}

export function createResolveTeamStep<T extends { message: Message; headers: EventHeaders; event: IncomingEvent }>(
    hub: Hub
): ProcessingStep<T, T & { eventWithTeam: IncomingEventWithTeam }> {
    return async function resolveTeamStep(input) {
        const { message, headers, event } = input

        const eventWithTeam = await resolveTeam(hub, message, headers, event.event)

        if (!eventWithTeam) {
            return drop('Failed to resolve team')
        }

        return ok({ ...input, eventWithTeam })
    }
}
