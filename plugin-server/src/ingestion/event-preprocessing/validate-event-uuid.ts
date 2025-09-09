import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { Hub, IncomingEventWithTeam } from '../../types'
import { UUID } from '../../utils/utils'
import { drop, success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { AsyncPreprocessingStep } from '../processing-pipeline'

export async function validateEventUuid(
    eventWithTeam: IncomingEventWithTeam,
    hub: Pick<Hub, 'db'>
): Promise<IncomingEventWithTeam | null> {
    const { event, team } = eventWithTeam

    if (!event.uuid) {
        await captureIngestionWarning(hub.db.kafkaProducer, team.id, 'skipping_event_invalid_uuid', {
            eventUuid: JSON.stringify(event.uuid),
        })
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'empty_uuid',
            })
            .inc()
        return null
    }

    if (!UUID.validateString(event.uuid, false)) {
        await captureIngestionWarning(hub.db.kafkaProducer, team.id, 'skipping_event_invalid_uuid', {
            eventUuid: JSON.stringify(event.uuid),
        })
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_uuid',
            })
            .inc()
        return null
    }

    return eventWithTeam
}

export function createValidateEventUuidStep(
    hub: Hub
): AsyncPreprocessingStep<IncomingEventWithTeam, IncomingEventWithTeam> {
    return async (eventWithTeam) => {
        const validEvent = await validateEventUuid(eventWithTeam, hub)
        if (!validEvent) {
            return drop('Event has invalid UUID')
        }

        return success(validEvent)
    }
}
