import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventHeaders, Hub, IncomingEvent, IncomingEventWithTeam } from '../../types'
import { tokenOrTeamPresentCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { drop, success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { AsyncPreprocessingStep } from '../preprocessing-pipeline'

export async function resolveTeam(
    hub: Pick<Hub, 'teamManager'>,
    incomingEvent: IncomingEvent
): Promise<IncomingEventWithTeam | null> {
    const event = incomingEvent.event

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
        message: incomingEvent.message,
        headers: incomingEvent.headers,
    }
}

export function createResolveTeamStep(
    hub: Hub
): AsyncPreprocessingStep<
    { message: Message; headers: EventHeaders; event: IncomingEvent },
    { message: Message; headers: EventHeaders; eventWithTeam: IncomingEventWithTeam }
> {
    return async (input) => {
        const { message, headers, event } = input

        const eventWithHeaders = { ...event, headers }
        const eventWithTeam = await resolveTeam(hub, eventWithHeaders)

        if (!eventWithTeam) {
            return drop('Failed to resolve team')
        }

        return success({ message, headers, eventWithTeam })
    }
}
