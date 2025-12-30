import { Counter } from 'prom-client'

import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager, Restriction } from '../../utils/event-ingestion-restriction-manager'
import { dlq, drop, ok, redirect } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export const ingestionOverflowingMessagesTotal = new Counter({
    name: 'ingestion_overflowing_messages_total',
    help: 'Count of messages rerouted to the overflow topic.',
})

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
        const { token } = headers ?? {}

        const restrictions = manager.getAppliedRestrictions(token, headers)

        if (restrictions.size === 0) {
            return Promise.resolve(ok(input))
        }

        // Priority 1: Drop
        if (restrictions.has(Restriction.DROP_EVENT)) {
            return drop('blocked_token')
        }

        // Priority 2: DLQ
        if (restrictions.has(Restriction.REDIRECT_TO_DLQ)) {
            return dlq('restricted_to_dlq')
        }

        // Priority 3: Overflow
        if (routingConfig.overflowEnabled && restrictions.has(Restriction.FORCE_OVERFLOW)) {
            ingestionOverflowingMessagesTotal.inc()
            const shouldProcessPerson = !restrictions.has(Restriction.SKIP_PERSON_PROCESSING)
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
