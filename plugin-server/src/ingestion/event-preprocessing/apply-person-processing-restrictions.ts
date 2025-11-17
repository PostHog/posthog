import { IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyPersonProcessingRestrictions(
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

// TODO: Refactor this to use just headers and the team before parsing the event
export function createApplyPersonProcessingRestrictionsStep<T extends { eventWithTeam: IncomingEventWithTeam }>(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): ProcessingStep<T, T> {
    return async function applyPersonProcessingRestrictionsStep(input) {
        const { eventWithTeam } = input
        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)
        return Promise.resolve(ok(input))
    }
}
