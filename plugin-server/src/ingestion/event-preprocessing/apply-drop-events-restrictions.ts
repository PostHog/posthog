import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'

export function applyDropEventsRestrictions(
    message: Message,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): Message | null {
    let distinctId: string | undefined
    let token: string | undefined

    message.headers?.forEach((header) => {
        if ('distinct_id' in header) {
            distinctId = header['distinct_id'].toString()
        }
        if ('token' in header) {
            token = header['token'].toString()
        }
    })

    if (eventIngestionRestrictionManager.shouldDropEvent(token, distinctId)) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'blocked_token',
            })
            .inc()
        return null
    }

    return message
}
