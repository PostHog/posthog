import { ingestionOverflowingMessagesTotal } from '../../main/ingestion-queues/batch-processing/metrics'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { dlq, drop, ok, redirect } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type RoutingConfig = {
    overflowTopic: string
    overflowEnabled: boolean
    preservePartitionLocality: boolean
}

export function createApplyEventRestrictionsStep<T extends { headers: EventHeaders }>(
    manager: EventIngestionRestrictionManager,
    routingConfig: RoutingConfig
): ProcessingStep<T, T> {
    return async function applyEventRestrictionsStep(input) {
        const { headers } = input
        const {
            distinct_id: distinctId,
            session_id: sessionId,
            event: eventName,
            uuid: eventUuid,
            token,
        } = headers ?? {}

        // Priority 1: Drop
        if (manager.shouldDropEvent(token, distinctId, sessionId, eventName, eventUuid)) {
            return drop('blocked_token')
        }

        // Priority 2: DLQ
        if (manager.shouldRedirectToDlq(token, distinctId, sessionId, eventName, eventUuid)) {
            return dlq('restricted_to_dlq')
        }

        // Priority 3: Overflow
        if (
            routingConfig.overflowEnabled &&
            manager.shouldForceOverflow(token, distinctId, sessionId, eventName, eventUuid)
        ) {
            ingestionOverflowingMessagesTotal.inc()
            const shouldSkipPerson = manager.shouldSkipPerson(token, distinctId, sessionId, eventName, eventUuid)
            const preserveKey = shouldSkipPerson ? routingConfig.preservePartitionLocality : true
            return redirect(
                'Event redirected to overflow due to force overflow restrictions',
                routingConfig.overflowTopic,
                preserveKey,
                false
            )
        }

        return Promise.resolve(ok(input))
    }
}
