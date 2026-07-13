import { Counter } from 'prom-client'

import { OVERFLOW_OUTPUT, OverflowOutput } from '~/common/outputs'
import { EventIngestionRestrictionManager, RestrictionType } from '~/common/utils/event-ingestion-restrictions'
import { IngestionOverflowMode } from '~/ingestion/config'
import { dlq, drop, ok, redirect } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders } from '~/types'

export const ingestionOverflowingMessagesTotal = new Counter({
    name: 'ingestion_overflowing_messages_total',
    help: 'Count of messages rerouted to the overflow topic.',
})

export type RoutingConfig = {
    overflowMode: IngestionOverflowMode
    preservePartitionLocality: boolean
}

/**
 * Drop + DLQ token restrictions only, no overflow handling. For pipelines
 * that don't have an overflow topic (e.g. client warnings). Type signature
 * has no side outputs, so callers don't need to include `OverflowOutput` in
 * their pipeline's outputs union just to satisfy the step.
 */
export function createApplyBasicEventRestrictionsStep<T extends { headers: EventHeaders }>(
    manager: EventIngestionRestrictionManager
): ProcessingStep<T, T> {
    return function applyBasicEventRestrictionsStep(input) {
        const { headers } = input

        const restrictions = manager.getAppliedRestrictions(headers.token, headers)

        if (restrictions.has(RestrictionType.DROP_EVENT)) {
            return Promise.resolve(drop('blocked_token'))
        }

        if (restrictions.has(RestrictionType.REDIRECT_TO_DLQ)) {
            return Promise.resolve(dlq('restricted_to_dlq'))
        }

        return Promise.resolve(ok(input))
    }
}

export function createApplyEventRestrictionsStep<T extends { headers: EventHeaders }>(
    manager: EventIngestionRestrictionManager,
    routingConfig: RoutingConfig
): ProcessingStep<T, T, OverflowOutput> {
    return async function applyEventRestrictionsStep(input) {
        const { headers } = input

        const restrictions = manager.getAppliedRestrictions(headers.token, headers)

        if (restrictions.size === 0) {
            return Promise.resolve(ok(input))
        }

        // Priority 1: Drop
        if (restrictions.has(RestrictionType.DROP_EVENT)) {
            return drop('blocked_token')
        }

        // Priority 2: DLQ
        if (restrictions.has(RestrictionType.REDIRECT_TO_DLQ)) {
            return dlq('restricted_to_dlq')
        }

        // Priority 3: Overflow
        if (routingConfig.overflowMode === 'redirect' && restrictions.has(RestrictionType.FORCE_OVERFLOW)) {
            ingestionOverflowingMessagesTotal.inc()
            const shouldProcessPerson = !restrictions.has(RestrictionType.SKIP_PERSON_PROCESSING)
            const preservePartitionLocality = shouldProcessPerson ? true : routingConfig.preservePartitionLocality
            return redirect(
                'Event redirected to overflow due to force overflow restrictions',
                OVERFLOW_OUTPUT,
                preservePartitionLocality,
                false
            )
        }

        return Promise.resolve(ok(input))
    }
}
