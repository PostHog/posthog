import { IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'

export function applyPersonProcessingRestrictions(
    eventWithTeam: IncomingEventWithTeam,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): void {
    const { event, team } = eventWithTeam

    const shouldSkipPersonRestriction = eventIngestionRestrictionManager.shouldSkipPerson(
        event.token,
        event.distinct_id
    )
    const shouldSkipPersonOptOut = team.person_processing_opt_out
    const shouldSkipPerson = shouldSkipPersonRestriction || shouldSkipPersonOptOut

    if (shouldSkipPerson) {
        if (event.properties) {
            event.properties.$process_person_profile = false
        } else {
            event.properties = { $process_person_profile: false }
        }
    }
}
