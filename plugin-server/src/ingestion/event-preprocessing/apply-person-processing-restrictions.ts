import { IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../processing-pipeline'

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
): SyncPreprocessingStep<T, T> {
    return (input) => {
        const { eventWithTeam } = input
        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)
        return success(input)
    }
}
