import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'

export function applyDropEventsRestrictions(
    message: Message,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): Message | null {
    let distinctId: string | undefined
    let token: string | undefined

    // Parse the headers so we can early exit if found and should be dropped
    message.headers?.forEach((header) => {
        if (header.key === 'distinct_id') {
            distinctId = header.value.toString()
        }
        if (header.key === 'token') {
            token = header.value.toString()
        }
    })

    if (!token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'missing_token',
            })
            .inc()
        return null
    }

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
