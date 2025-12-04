import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyDropEventsRestrictions(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers?: EventHeaders
): boolean {
    const distinctId = headers?.distinct_id
    const sessionId = headers?.session_id
    const eventName = headers?.event
    const eventUuid = headers?.uuid
    const token = headers?.token

    return eventIngestionRestrictionManager.shouldDropEvent(token, distinctId, sessionId, eventName, eventUuid)
}

export function createApplyDropRestrictionsStep<T extends { headers: EventHeaders }>(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): ProcessingStep<T, T> {
    return async function applyDropRestrictionsStep(input) {
        const { headers } = input

        if (applyDropEventsRestrictions(eventIngestionRestrictionManager, headers)) {
            return drop('blocked_token')
        }

        return Promise.resolve(ok(input))
    }
}
