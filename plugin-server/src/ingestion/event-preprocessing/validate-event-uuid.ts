import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { Hub, IncomingEventWithTeam } from '../../types'
import { UUID } from '../../utils/utils'
import { captureIngestionWarning } from '../../worker/ingestion/utils'

export async function validateEventUuid(
    eventWithTeam: IncomingEventWithTeam,
    hub: Pick<Hub, 'db'>
): Promise<IncomingEventWithTeam | null> {
    const { event, team } = eventWithTeam

    // Check for an invalid UUID, which should be blocked by capture, when team_id is present
    if (!UUID.validateString(event.uuid, false)) {
        await captureIngestionWarning(hub.db.kafkaProducer, team.id, 'skipping_event_invalid_uuid', {
            eventUuid: JSON.stringify(event.uuid),
        })
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: event.uuid ? 'invalid_uuid' : 'empty_uuid',
            })
            .inc()
        return null
    }

    return eventWithTeam
}
