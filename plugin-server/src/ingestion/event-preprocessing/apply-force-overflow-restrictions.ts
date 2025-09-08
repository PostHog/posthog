import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { redirect, success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../preprocessing-pipeline'

export type ForceOverflowDecision = {
    shouldRedirect: boolean
    preservePartitionLocality?: boolean
}

export function applyForceOverflowRestrictions(
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

export function createApplyForceOverflowRestrictionsStep(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    overflowEnabled: boolean,
    forcedOverflowEventsCounter?: Counter<string>,
    pendingOverflowMessages?: Array<{ message: Message; preservePartitionLocality?: boolean }>
): SyncPreprocessingStep<{ message: Message; headers: EventHeaders }, { message: Message; headers: EventHeaders }> {
    return (input) => {
        const { message, headers } = input

        const forceOverflowDecision = applyForceOverflowRestrictions(eventIngestionRestrictionManager, headers)
        if (forceOverflowDecision.shouldRedirect && overflowEnabled) {
            if (forcedOverflowEventsCounter) {
                forcedOverflowEventsCounter.inc()
            }
            if (pendingOverflowMessages) {
                pendingOverflowMessages.push({
                    message,
                    preservePartitionLocality: forceOverflowDecision.preservePartitionLocality,
                })
            }

            return redirect('Event redirected to overflow due to force overflow restrictions', 'overflow')
        }

        return success({ message, headers })
    }
}
