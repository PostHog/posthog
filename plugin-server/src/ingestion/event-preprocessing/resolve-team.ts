import { Hub, IncomingEvent, IncomingEventWithTeam } from '../../types'
import { populateTeamDataStep } from '../../worker/ingestion/event-pipeline/populateTeamDataStep'

export async function resolveTeam(
    hub: Pick<Hub, 'teamManager'>,
    incomingEvent: IncomingEvent
): Promise<IncomingEventWithTeam | null> {
    const result = await populateTeamDataStep(hub, incomingEvent.event)
    if (!result) {
        return null
    }
    return {
        event: result.event,
        team: result.team,
        message: incomingEvent.message,
    }
}
