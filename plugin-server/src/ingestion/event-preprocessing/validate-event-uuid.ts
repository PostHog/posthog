import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { Hub, IncomingEventWithTeam } from '../../types'
import { UUID } from '../../utils/utils'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

async function isEventUuidValid(eventWithTeam: IncomingEventWithTeam, hub: Pick<Hub, 'db'>): Promise<boolean> {
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
        return false
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
        return false
    }

    return true
}

export function createValidateEventUuidStep<T extends { eventWithTeam: IncomingEventWithTeam }>(
    hub: Hub
): ProcessingStep<T, T> {
    return async function validateEventUuidStep(input) {
        const { eventWithTeam } = input
        const isValid = await isEventUuidValid(eventWithTeam, hub)
        if (!isValid) {
            return drop('Event has invalid UUID')
        }
        return ok(input)
    }
}
