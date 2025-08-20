import { Message } from 'node-rdkafka'

import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'

export type ForceOverflowDecision = {
    shouldRedirect: boolean
    preservePartitionLocality?: boolean
}

export function applyForceOverflowRestrictions(
    message: Message,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): ForceOverflowDecision {
    let distinctId: string | undefined
    let token: string | undefined

    message.headers?.forEach((header) => {
        if ('distinct_id' in header) {
            distinctId = header['distinct_id'].toString()
        }
        if ('token' in header) {
            token = header['token'].toString()
        }
    })

    const shouldForceOverflow = eventIngestionRestrictionManager.shouldForceOverflow(token, distinctId)

    if (!shouldForceOverflow) {
        return { shouldRedirect: false }
    }

    const shouldSkipPerson = eventIngestionRestrictionManager.shouldSkipPerson(token, distinctId)
    const preservePartitionLocality = shouldForceOverflow && !shouldSkipPerson ? true : undefined

    return { shouldRedirect: true, preservePartitionLocality }
}
