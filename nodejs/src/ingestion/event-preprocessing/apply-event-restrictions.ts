import { Counter } from 'prom-client'

import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
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

        const restrictions = manager.getAppliedRestrictions(headers.token, headers)

        if (restrictions.isEmpty) {
            return Promise.resolve(ok(input))
        }

        if (restrictions.drop) {
            return drop('blocked_token')
        }

        if (restrictions.redirectToDlq) {
            return dlq('restricted_to_dlq')
        }

        const redirectTopic = restrictions.redirectToTopic
        if (redirectTopic) {
            return redirect('restricted_to_topic', redirectTopic, true, false)
        }

        if (routingConfig.overflowEnabled && restrictions.forceOverflow) {
            ingestionOverflowingMessagesTotal.inc()
            const shouldProcessPerson = !restrictions.skipPersonProcessing
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
