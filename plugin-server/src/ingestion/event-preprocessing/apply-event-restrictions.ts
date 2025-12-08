import { ingestionOverflowingMessagesTotal } from '../../main/ingestion-queues/batch-processing/metrics'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager, Restriction } from '../../utils/event-ingestion-restriction-manager'
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

        const restrictions = manager.getAppliedRestrictions(token, distinctId, sessionId, eventName, eventUuid)

        // Priority 1: Drop
        if (restrictions.includes(Restriction.DROP_EVENT)) {
            return drop('blocked_token')
        }

        // Priority 2: DLQ
        if (restrictions.includes(Restriction.REDIRECT_TO_DLQ)) {
            return dlq('restricted_to_dlq')
        }

        // Priority 3: Overflow
        if (routingConfig.overflowEnabled && restrictions.includes(Restriction.FORCE_OVERFLOW)) {
            ingestionOverflowingMessagesTotal.inc()
            const shouldProcessPerson = !restrictions.includes(Restriction.SKIP_PERSON_PROCESSING)
            const preservePartitionLocality = shouldProcessPerson ? true : routingConfig.preservePartitionLocality
            return redirect(
                'Event redirected to overflow due to force overflow restrictions',
                routingConfig.overflowTopic,
                preservePartitionLocality,
                false
            )
        }

        return Promise.resolve(ok(input))
    }
}
