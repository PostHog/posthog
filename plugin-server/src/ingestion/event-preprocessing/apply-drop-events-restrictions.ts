import { Message } from 'node-rdkafka'

import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { drop, success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../preprocessing-pipeline'

export function applyDropEventsRestrictions(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers?: EventHeaders
): boolean {
    const distinctId = headers?.distinct_id
    const token = headers?.token

    return eventIngestionRestrictionManager.shouldDropEvent(token, distinctId)
}

export function createApplyDropRestrictionsStep(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): SyncPreprocessingStep<{ message: Message; headers: EventHeaders }, { message: Message; headers: EventHeaders }> {
    return (input) => {
        const { message, headers } = input

        if (applyDropEventsRestrictions(eventIngestionRestrictionManager, headers)) {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics',
                    drop_cause: 'blocked_token',
                })
                .inc()
            return drop('Event dropped due to token restrictions')
        }

        return success({ message, headers })
    }
}
