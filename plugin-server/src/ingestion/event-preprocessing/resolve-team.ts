import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { Hub, IncomingEvent, IncomingEventWithTeam } from '../../types'
import { tokenOrTeamPresentCounter } from '../../worker/ingestion/event-pipeline/metrics'

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

    let team = null
    // Events with no token or team_id are dropped, they should be blocked by capture
    if (!event.token && !event.team_id) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return null
    } else if (event.team_id) {
        team = await hub.teamManager.getTeam(event.team_id)
    } else if (event.token) {
        team = await hub.teamManager.getTeamByToken(event.token)
    }

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
    }
}
