import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyPersonProcessingRestrictions(
    eventWithTeam: IncomingEventWithTeam,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager,
    headers: EventHeaders
): void {
    const { event, team } = eventWithTeam

    const shouldSkipPersonRestriction = eventIngestionRestrictionManager.shouldSkipPerson(
        headers.token,
        headers.distinct_id,
        headers.session_id,
        headers.event,
        headers.uuid
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

export function createApplyPersonProcessingRestrictionsStep<
    T extends { eventWithTeam: IncomingEventWithTeam; headers: EventHeaders },
>(eventIngestionRestrictionManager: EventIngestionRestrictionManager): ProcessingStep<T, T> {
    return async function applyPersonProcessingRestrictionsStep(input) {
        const { eventWithTeam, headers } = input
        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager, headers)
        return Promise.resolve(ok(input))
    }
}
