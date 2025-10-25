import { ingestionOverflowingMessagesTotal } from '../../main/ingestion-queues/batch-processing/metrics'
import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok, redirect } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type ForceOverflowDecision = {
    shouldRedirect: boolean
    preservePartitionLocality?: boolean
}

export type OverflowConfig = {
    overflowTopic: string
    preservePartitionLocality: boolean
    overflowEnabled: boolean
}

function applyForceOverflowRestrictions(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers?: EventHeaders
): ForceOverflowDecision {
    const distinctId = headers?.distinct_id
    const token = headers?.token

    const shouldForceOverflow = eventIngestionRestrictionManager.shouldForceOverflow(token, distinctId)

    if (!shouldForceOverflow) {
        return { shouldRedirect: false }
    }

    const shouldSkipPerson = eventIngestionRestrictionManager.shouldSkipPerson(token, distinctId)
    const preservePartitionLocality = shouldForceOverflow && !shouldSkipPerson ? true : undefined

    return { shouldRedirect: true, preservePartitionLocality }
}

export function createApplyForceOverflowRestrictionsStep<T extends { headers: EventHeaders }>(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    overflowConfig: OverflowConfig
): ProcessingStep<T, T> {
    return async function applyForceOverflowRestrictionsStep(input) {
        const { headers } = input

        if (!overflowConfig.overflowEnabled) {
            return Promise.resolve(ok(input))
        }

        const forceOverflowDecision = applyForceOverflowRestrictions(eventIngestionRestrictionManager, headers)
        if (!forceOverflowDecision.shouldRedirect) {
            return Promise.resolve(ok(input))
        }

        ingestionOverflowingMessagesTotal.inc()

        const preservePartitionLocality =
            forceOverflowDecision.preservePartitionLocality !== undefined
                ? forceOverflowDecision.preservePartitionLocality
                : overflowConfig.preservePartitionLocality
        return Promise.resolve(
            redirect(
                'Event redirected to overflow due to force overflow restrictions',
                overflowConfig.overflowTopic,
                preservePartitionLocality,
                false
            )
        )
    }
}
