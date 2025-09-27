import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { Hub, IncomingEventWithTeam } from '../../types'
import { captureIngestionWarning } from '../../worker/ingestion/utils'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createValidateEventPropertiesStep<T extends { eventWithTeam: IncomingEventWithTeam }>(
    hub: Hub
): ProcessingStep<T, T> {
    return async function validateEventPropertiesStep(input) {
        const { eventWithTeam } = input
        const { event, team } = eventWithTeam

        // Validate $groupidentify group_key length
        if (event.event === '$groupidentify') {
            const groupKey = event.properties?.$group_key
            if (groupKey && groupKey.toString().length > 400) {
                await captureIngestionWarning(
                    hub.db.kafkaProducer,
                    team.id,
                    'group_key_too_long',
                    {
                        eventUuid: event.uuid,
                        event: event.event,
                        distinctId: event.distinct_id,
                        groupKey,
                        groupKeyLength: groupKey.toString().length,
                        maxLength: 400,
                    },
                    { alwaysSend: false }
                )
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'group_key_too_long',
                    })
                    .inc()
                return drop('Group key too long')
            }
        }

        return ok(input)
    }
}
