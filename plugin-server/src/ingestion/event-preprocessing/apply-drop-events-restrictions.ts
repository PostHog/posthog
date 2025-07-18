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
        Object.keys(header).forEach((key) => {
            if (key === 'distinct_id') {
                distinctId = header[key].toString()
            }
            if (key === 'token') {
                token = header[key].toString()
            }
        })
    })

    if (token && eventIngestionRestrictionManager.shouldDropEvent(token, distinctId)) {
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
