import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'

export function applyDropEventsRestrictions(
    message: Message,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers?: EventHeaders
): Message | null {
    const distinctId = headers?.distinct_id
    const token = headers?.token

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
