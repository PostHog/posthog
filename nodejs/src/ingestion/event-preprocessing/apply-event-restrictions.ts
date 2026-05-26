import { Counter } from 'prom-client'

import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager, RestrictionType } from '../../utils/event-ingestion-restrictions'
import { OVERFLOW_OUTPUT, OverflowOutput } from '../common/outputs'
import { PipelineResult, dlq, drop, ok, redirect } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export const ingestionOverflowingMessagesTotal = new Counter({
    name: 'ingestion_overflowing_messages_total',
    help: 'Count of messages rerouted to the overflow topic.',
})

export type RoutingConfig = {
    overflowEnabled: boolean
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
    return function applyBasicEventRestrictionsStep(input): Promise<PipelineResult<T>> {
        return Promise.resolve(applyDropAndDlq(manager, input) ?? ok(input))
    }
}

export function createApplyEventRestrictionsStep<T extends { headers: EventHeaders }>(
    manager: EventIngestionRestrictionManager,
    routingConfig: RoutingConfig
): ProcessingStep<T, T, OverflowOutput> {
    return function applyEventRestrictionsStep(input) {
        const dropOrDlq = applyDropAndDlq(manager, input)
        if (dropOrDlq) {
            return Promise.resolve(dropOrDlq)
        }

        const restrictions = manager.getAppliedRestrictions(input.headers.token, input.headers)
        if (routingConfig.overflowEnabled && restrictions.has(RestrictionType.FORCE_OVERFLOW)) {
            ingestionOverflowingMessagesTotal.inc()
            const shouldProcessPerson = !restrictions.has(RestrictionType.SKIP_PERSON_PROCESSING)
            const preservePartitionLocality = shouldProcessPerson ? true : routingConfig.preservePartitionLocality
            return Promise.resolve(
                redirect(
                    'Event redirected to overflow due to force overflow restrictions',
                    OVERFLOW_OUTPUT,
                    preservePartitionLocality,
                    false
                )
            )
        }

        return Promise.resolve(ok(input))
    }
}

function applyDropAndDlq<T extends { headers: EventHeaders }>(
    manager: EventIngestionRestrictionManager,
    input: T
): PipelineResult<T> | null {
    const restrictions = manager.getAppliedRestrictions(input.headers.token, input.headers)

    if (restrictions.size === 0) {
        return null
    }
    if (restrictions.has(RestrictionType.DROP_EVENT)) {
        return drop('blocked_token')
    }
    if (restrictions.has(RestrictionType.REDIRECT_TO_DLQ)) {
        return dlq('restricted_to_dlq')
    }
    return null
}
