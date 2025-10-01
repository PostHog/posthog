import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyDropEventsRestrictions(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers?: EventHeaders
): boolean {
    const distinctId = headers?.distinct_id
    const token = headers?.token

    return eventIngestionRestrictionManager.shouldDropEvent(token, distinctId)
}

export function createApplyDropRestrictionsStep<T extends { headers: EventHeaders }>(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): ProcessingStep<T, T> {
    return async function applyDropRestrictionsStep(input) {
        const { headers } = input

        if (applyDropEventsRestrictions(eventIngestionRestrictionManager, headers)) {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics',
                    drop_cause: 'blocked_token',
                })
                .inc()
            return drop('Event dropped due to token restrictions')
        }

        return Promise.resolve(ok(input))
    }
}
