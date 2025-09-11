import { EventHeaders } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'

export function applyDropEventsRestrictions(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers?: EventHeaders
): boolean {
    const distinctId = headers?.distinct_id
    const token = headers?.token

    return eventIngestionRestrictionManager.shouldDropEvent(token, distinctId)
}
